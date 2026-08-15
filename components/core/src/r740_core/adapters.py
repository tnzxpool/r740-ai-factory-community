# SPDX-License-Identifier: LGPL-3.0-or-later
"""Authenticated loopback adapters and explicit R740 task-family runners."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from typing import Any, Protocol
import urllib.error
import urllib.parse
import urllib.request

from .autorouting import DEFAULT_MODEL, ExecutionError
from .config import SETTINGS


MODEL_ENDPOINTS = SETTINGS.model_endpoints
ALLOWED_PORTS = {
    urllib.parse.urlsplit(url).port
    for url in (*MODEL_ENDPOINTS.values(), SETTINGS.model_manager_url, SETTINGS.graphics_manager_url)
}


class Transport(Protocol):
    def json(self, method: str, url: str, *, payload: dict[str, Any] | None = None,
             key: str, timeout: float, bearer: bool = False) -> dict[str, Any]: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LoopbackJSONTransport:
    """Bounded JSON transport that cannot follow redirects or leave loopback."""

    def __init__(self, *, max_response_bytes: int = 8 * 1024 * 1024):
        self.max_response_bytes = max_response_bytes
        self.opener = urllib.request.build_opener(_NoRedirect)

    @staticmethod
    def _validate(url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.port not in ALLOWED_PORTS or parsed.username or parsed.password
                or parsed.fragment):
            raise ExecutionError("non-loopback endpoint rejected")

    def json(self, method: str, url: str, *, payload: dict[str, Any] | None = None,
             key: str, timeout: float, bearer: bool = False) -> dict[str, Any]:
        self._validate(url)
        if not key:
            raise ExecutionError("internal credential unavailable")
        data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        headers["Authorization" if bearer else "X-Internal-Key"] = f"Bearer {key}" if bearer else key
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(self.max_response_bytes + 1)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise ExecutionError(f"local adapter failed: {type(exc).__name__}") from exc
        if len(raw) > self.max_response_bytes:
            raise ExecutionError("local response exceeds limit")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExecutionError("invalid local JSON response") from exc
        if not isinstance(value, dict):
            raise ExecutionError("local response must be an object")
        return value


class ModelControllerAdapter:
    def __init__(self, transport: Transport, key: str, *, manager_url: str = SETTINGS.model_manager_url,
                 graphics_url: str = SETTINGS.graphics_manager_url):
        self.transport, self.key = transport, key
        self.manager_url, self.graphics_url = manager_url.rstrip("/"), graphics_url.rstrip("/")

    def status(self) -> dict[str, Any]:
        value = self.transport.json("GET", f"{self.manager_url}/v1/models/status", key=self.key, timeout=8)
        specialists = self.transport.json(
            "GET", f"{self.manager_url}/v1/autorouting/specialists", key=self.key, timeout=8
        )
        graphics = self.transport.json(
            "GET", f"{self.graphics_url}/v1/graphics/status", key=self.key, timeout=8
        )
        models = value.setdefault("models", {})
        if not isinstance(models, dict):
            raise ExecutionError("invalid controller model status")
        models["glm-ocr-q8"] = {"available": specialists.get("glm-ocr-q8") is True}
        models["sdxl-1.0"] = {"available": graphics.get("available") is True}
        value["graphics_state"] = str(graphics.get("state", "unknown"))
        return value

    def switch(self, model_id: str) -> dict[str, Any]:
        return self.transport.json(
            "POST", f"{self.manager_url}/v1/models/switch", payload={"model_id": model_id},
            key=self.key, timeout=460,
        )

    def restore_default(self, reason: str) -> dict[str, Any]:
        graphics = self.transport.json(
            "POST", f"{self.graphics_url}/v1/graphics/release", payload={},
            key=self.key, timeout=320,
        )
        if graphics.get("state") != "cold":
            raise ExecutionError("graphics manager did not release before Qwen3.6 restore")
        restored = self.transport.json(
            "POST", f"{self.manager_url}/v1/models/restore-default",
            payload={"reason": reason[:160]}, key=self.key, timeout=460,
        )
        restored["graphics_cold"] = True
        restored["one_heavy"] = restored.get("one_heavy") is True
        return restored


def _messages(payload: dict[str, Any], *, vision: bool) -> list[dict[str, Any]]:
    messages = payload.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 64:
        raise ExecutionError("invalid messages")
    encoded = json.dumps(messages, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 12 * 1024 * 1024:
        raise ExecutionError("task payload too large")
    if "http://" in encoded or "https://" in encoded:
        raise ExecutionError("external content URL rejected")
    if vision and "data:image/" not in encoded:
        raise ExecutionError("vision requires an inline image")
    return messages


class RunnerDispatcher:
    """Dispatch typed tasks; it never executes model-produced tools or shell code."""

    def __init__(self, transport: Transport, internal_key: str, backend_key: str,
                 tasks: list[dict[str, Any]], payloads: dict[str, dict[str, Any]], *,
                 manager_url: str = SETTINGS.model_manager_url,
                 graphics_url: str = SETTINGS.graphics_manager_url):
        self.transport, self.internal_key, self.backend_key = transport, internal_key, backend_key
        self.manager_url, self.graphics_url = manager_url.rstrip("/"), graphics_url.rstrip("/")
        self.kinds = {str(task["id"]): str(task["kind"]) for task in tasks}
        self.payloads = payloads

    def __call__(self, task_id: str, model_id: str) -> dict[str, Any]:
        if task_id not in self.kinds or task_id not in self.payloads:
            raise ExecutionError("missing typed task payload")
        kind, payload = self.kinds[task_id], self.payloads[task_id]
        if not isinstance(payload, dict):
            raise ExecutionError("task payload must be an object")
        if kind in {"general_chat", "structured_output", "coding", "frontend_ui", "tool_execution"}:
            return self._text(model_id, payload)
        if kind == "vision_ocr":
            return self._vision(model_id, payload)
        if kind == "document_retrieval":
            return self._ocr(model_id, payload)
        if kind == "image_generation":
            return self._sdxl(model_id, payload)
        raise ExecutionError("runner unavailable")

    def _completion(self, model_id: str, payload: dict[str, Any], *, vision: bool) -> dict[str, Any]:
        endpoint = MODEL_ENDPOINTS.get(model_id)
        if not endpoint:
            raise ExecutionError("no local endpoint for selected model")
        body = {
            "model": model_id,
            "messages": _messages(payload, vision=vision),
            "temperature": max(0.0, min(float(payload.get("temperature", 0.2)), 1.0)),
            "max_tokens": max(1, min(int(payload.get("max_tokens", 1024)), 4096)),
            "stream": False,
        }
        if model_id == DEFAULT_MODEL:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        result = self.transport.json(
            "POST", f"{endpoint}/v1/chat/completions", payload=body,
            key=self.backend_key, timeout=300, bearer=True,
        )
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExecutionError("completion response missing content") from exc
        if not str(content).strip():
            raise ExecutionError("completion returned empty content")
        return result

    def _text(self, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._completion(model_id, payload, vision=False)

    def _vision(self, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if model_id != "qwen3-vl-8b":
            raise ExecutionError("vision task routed to a non-vision model")
        return self._completion(model_id, payload, vision=True)

    def _ocr(self, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if model_id != "glm-ocr-q8" or set(payload) != {"image_base64", "image_sha256"}:
            raise ExecutionError("invalid OCR transaction")
        try:
            raw = base64.b64decode(str(payload["image_base64"]), validate=True)
        except (ValueError, TypeError) as exc:
            raise ExecutionError("invalid OCR image") from exc
        if not raw or len(raw) > 12 * 1024 * 1024:
            raise ExecutionError("invalid OCR image size")
        if not re.fullmatch(r"[0-9a-f]{64}", str(payload["image_sha256"])):
            raise ExecutionError("invalid OCR digest")
        if not hashlib.sha256(raw).hexdigest() == payload["image_sha256"]:
            raise ExecutionError("OCR digest mismatch")
        return self.transport.json(
            "POST", f"{self.manager_url}/v1/internal/ocr/extract", payload=payload,
            key=self.internal_key, timeout=1220,
        )

    def _release_graphics(self) -> None:
        """Wait for any just-submitted job to become releasable, then prove cold."""
        last_error: BaseException | None = None
        for attempt in range(360):
            try:
                released = self.transport.json(
                    "POST", f"{self.graphics_url}/v1/graphics/release",
                    payload={}, key=self.internal_key, timeout=20,
                )
                if released.get("state") != "cold":
                    raise ExecutionError("graphics manager did not report cold")
                return
            except Exception as exc:
                last_error = exc
                if attempt < 359:
                    time.sleep(1)
        raise ExecutionError("graphics manager did not release the P40") from last_error

    def _sdxl(self, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if model_id != "sdxl-1.0":
            raise ExecutionError("graphics task routed to wrong model")
        owner = str(payload.get("owner", ""))
        prompt = " ".join(str(payload.get("prompt", "")).replace("\x00", " ").split())
        if not re.fullmatch(r"user:[1-9][0-9]*", owner) or not 3 <= len(prompt) <= 1200:
            raise ExecutionError("invalid graphics owner or prompt")
        body = {
            "owner": owner, "prompt": prompt,
            "negative_prompt": str(payload.get("negative_prompt", ""))[:600],
            "width": int(payload.get("width", 768)), "height": int(payload.get("height", 768)),
            "steps": int(payload.get("steps", 24)),
        }
        cleanup_armed = False
        ready: dict[str, Any] | None = None
        primary_error: BaseException | None = None
        try:
            # Once the POST attempt begins, delivery is uncertain until a response
            # arrives: the manager may have accepted the job before the client saw
            # a timeout.  Arm cleanup before crossing that boundary.
            cleanup_armed = True
            job = self.transport.json(
                "POST", f"{self.graphics_url}/v1/graphics/jobs", payload=body,
                key=self.internal_key, timeout=40,
            )
            job_id = str(job.get("id", ""))
            if not re.fullmatch(r"[0-9a-f]{32}", job_id):
                raise ExecutionError("invalid graphics job id")
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                state = self.transport.json(
                    "GET", f"{self.graphics_url}/v1/graphics/jobs/{job_id}?owner={owner}",
                    key=self.internal_key, timeout=20,
                )
                if state.get("state") == "ready":
                    ready = state
                    break
                if state.get("state") == "failed":
                    raise ExecutionError("graphics job failed")
                time.sleep(1)
            if ready is None:
                raise ExecutionError("graphics job timeout")
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            if cleanup_armed:
                try:
                    self._release_graphics()
                except BaseException as release_exc:
                    if primary_error is not None:
                        raise ExecutionError("graphics task failed and P40 release also failed") from release_exc
                    raise
        return {**ready, "gpu_released": True}

