# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import asyncio
import json
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import SETTINGS
from .routing_planner import RoutingError, plan_workflow, routing_snapshot


DEFAULT_BACKEND_URL = SETTINGS.backend_url
EMBEDDING_URL = SETTINGS.embedding_url
MODEL_MANAGER_URL = SETTINGS.model_manager_url
GRAPHICS_MANAGER_URL = SETTINGS.graphics_manager_url
BACKEND_KEY = SETTINGS.backend_key
INTERNAL_KEY = SETTINGS.internal_key
REGISTRY_PATH = SETTINGS.registry_path
MODEL_STATE_PATH = SETTINGS.model_state_path
HOST_METRICS_PATH = SETTINGS.metrics_dir / "host_metrics.json"
MAX_REQUEST_BYTES = 1024 * 1024
MAX_OCR_REQUEST_BYTES = 900 * 1024
DEFAULT_MODEL_ID = "qwen3.6-35b-a3b-iq4xs"
MODEL_ENDPOINTS = SETTINGS.model_endpoints

app = FastAPI(title="AI Factory Orchestrator", version="1.0.0", docs_url=None, redoc_url=None)
inference_slot = asyncio.Semaphore(1)
_budget_cache: tuple[float, dict[str, Any]] | None = None


def require_internal_key(x_internal_key: str | None) -> None:
    if not INTERNAL_KEY or x_internal_key is None or not secrets.compare_digest(x_internal_key, INTERNAL_KEY):
        raise HTTPException(status_code=401, detail="accesso interno non autorizzato")


def read_registry() -> dict[str, Any]:
    try:
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "backends": {}, "models": {}, "ports": {}}


def active_backend() -> tuple[str, str]:
    try:
        state = json.loads(MODEL_STATE_PATH.read_text(encoding="utf-8"))
        model_id = str(state.get("active_model", DEFAULT_MODEL_ID))
    except (OSError, ValueError):
        model_id = DEFAULT_MODEL_ID
    if model_id not in MODEL_ENDPOINTS:
        model_id = DEFAULT_MODEL_ID
    return model_id, MODEL_ENDPOINTS[model_id]


def host_metrics_status() -> dict[str, Any]:
    try:
        value = json.loads(HOST_METRICS_PATH.read_text(encoding="utf-8"))
        sampled_epoch = int(value.get("sampled_epoch", 0))
        value["sample_age_seconds"] = max(int(time.time()) - sampled_epoch, 0) if sampled_epoch else None
        return value
    except (OSError, ValueError, json.JSONDecodeError):
        return {"available": False}


def gpu_status() -> dict[str, Any]:
    fields = "name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw"
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
            timeout=4,
        )
        values = [item.strip() for item in result.stdout.strip().split(",")]
        if len(values) != 7:
            raise ValueError("unexpected nvidia-smi output")
        return {
            "available": True,
            "name": values[0],
            "memory_total_mib": int(values[1]),
            "memory_used_mib": int(values[2]),
            "memory_free_mib": int(values[3]),
            "utilization_percent": int(values[4]),
            "temperature_c": int(values[5]),
            "power_w": float(values[6]),
        }
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"available": False}


def storage_status() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, path in (("ai", str(SETTINGS.state_dir)), ("root", "/")):
        try:
            usage = shutil.disk_usage(path)
            result[label] = {
                "total_gib": round(usage.total / 1024**3, 2),
                "used_gib": round(usage.used / 1024**3, 2),
                "free_gib": round(usage.free / 1024**3, 2),
                "used_percent": round(usage.used * 100 / usage.total, 1),
            }
        except OSError:
            result[label] = {"available": False}
    result["ai_budget"] = ai_budget_status()
    return result


def ai_budget_status() -> dict[str, Any]:
    global _budget_cache
    now = time.monotonic()
    if _budget_cache and now - _budget_cache[0] < 30:
        return _budget_cache[1]

    registry = read_registry()
    total_gib = float(registry.get("policy", {}).get("ai_budget_total_gib", 80))
    paths = [
        str(SETTINGS.models_dir),
        str(SETTINGS.state_dir / "cache"),
        str(SETTINGS.state_dir / "environments"),
        str(SETTINGS.results_dir),
        str(SETTINGS.state_dir / "logs"),
    ]
    try:
        completed = subprocess.run(
            ["du", "-sb", *paths], check=True, capture_output=True, text=True, timeout=10
        )
        used_bytes = sum(int(line.split()[0]) for line in completed.stdout.splitlines() if line.strip())
        used_gib = used_bytes / 1024**3
        value = {
            "total_gib": round(total_gib, 2),
            "used_gib": round(used_gib, 2),
            "free_gib": round(max(total_gib - used_gib, 0), 2),
            "used_percent": round(min(used_gib * 100 / total_gib, 100), 1),
        }
    except (OSError, subprocess.SubprocessError, ValueError):
        value = {"available": False, "total_gib": total_gib}
    _budget_cache = (now, value)
    return value


async def backend_health() -> dict[str, Any]:
    started = time.perf_counter()
    model_id, backend_url = active_backend()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{backend_url}/health")
            response.raise_for_status()
        return {
            "ready": True,
            "model": model_id,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except httpx.HTTPError as exc:
        return {"ready": False, "model": model_id, "error": exc.__class__.__name__}


async def graphics_status() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.get(
                f"{GRAPHICS_MANAGER_URL}/v1/graphics/status",
                headers={"X-Internal-Key": INTERNAL_KEY},
            )
        if response.status_code == 200:
            return response.json()
    except (httpx.HTTPError, ValueError):
        pass
    return {"available": False, "state": "unavailable", "warm": False, "queue_depth": 0}


async def release_idle_graphics_for_ocr() -> None:
    """Release only a warm/idle SDXL pipeline; never interrupt queued or active work."""
    status = await graphics_status()
    if not status.get("available"):
        raise HTTPException(status_code=503, detail="stato GPU grafica non disponibile")
    if status.get("active_job") or int(status.get("queue_depth", 0)) > 0:
        raise HTTPException(status_code=409, detail="generazione grafica attiva; OCR resta in attesa")
    if status.get("warm") or status.get("state") in {"warm", "releasing"}:
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    f"{GRAPHICS_MANAGER_URL}/v1/graphics/release",
                    headers={"X-Internal-Key": INTERNAL_KEY},
                )
            if response.status_code != 200:
                raise HTTPException(status_code=409, detail="GPU grafica non rilasciabile")
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="rilascio GPU grafica non disponibile")


def backend_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if BACKEND_KEY:
        headers["Authorization"] = f"Bearer {BACKEND_KEY}"
    return headers


@app.get("/health")
async def health() -> JSONResponse:
    backend = await backend_health()
    status = 200 if backend["ready"] else 503
    return JSONResponse({"status": "ok" if backend["ready"] else "degraded", "backend": backend}, status_code=status)


@app.get("/status")
async def status(x_internal_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_internal_key(x_internal_key)
    active_model, _ = active_backend()
    return {
        "service": "ai-factory-orchestrator",
        "active_model": active_model,
        "inference_busy": inference_slot.locked(),
        "backend": await backend_health(),
        "graphics": await graphics_status(),
        "gpu": gpu_status(),
        "storage": storage_status(),
        "host_metrics": host_metrics_status(),
        "registry": read_registry(),
    }


@app.get("/v1/models")
async def models(x_internal_key: str | None = Header(default=None)) -> JSONResponse:
    require_internal_key(x_internal_key)
    _, backend_url = active_backend()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{backend_url}/v1/models", headers=backend_headers())
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="backend modelli non disponibile")


@app.post("/v1/embeddings")
async def embeddings(request: Request, x_internal_key: str | None = Header(default=None)) -> JSONResponse:
    require_internal_key(x_internal_key)
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="richiesta embedding troppo grande")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON non valido")
    values = payload.get("input")
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list) or not values or len(values) > 32:
        raise HTTPException(status_code=400, detail="input embedding non valido")
    clean = [str(value)[:8000] for value in values]
    if any(not value for value in clean):
        raise HTTPException(status_code=400, detail="input embedding vuoto")
    safe_payload = {"model": "qwen3-embedding-0.6b", "input": clean}
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(f"{EMBEDDING_URL}/v1/embeddings", json=safe_payload)
        try:
            content = response.json()
        except ValueError:
            content = {"error": {"message": "risposta embedding non valida"}}
        return JSONResponse(content, status_code=response.status_code)
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="backend embedding non disponibile")


@app.post("/v1/chat/completions")
async def chat(request: Request, x_internal_key: str | None = Header(default=None)):
    require_internal_key(x_internal_key)
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="richiesta troppo grande")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON non valido")

    wants_stream = bool(payload.get("stream", False))
    active_model, backend_url = active_backend()
    requested_model = str(payload.get("model", active_model))
    if requested_model != active_model:
        raise HTTPException(
            status_code=409,
            detail="il modello attivo è cambiato; avvia una nuova chat",
        )
    if inference_slot.locked():
        raise HTTPException(status_code=429, detail="motore occupato; riprovare tra poco")

    if wants_stream:
        async def stream_backend():
            async with inference_slot:
                try:
                    async with httpx.AsyncClient(timeout=None) as client:
                        async with client.stream(
                            "POST",
                            f"{backend_url}/v1/chat/completions",
                            content=body,
                            headers=backend_headers(),
                        ) as response:
                            if response.status_code >= 400:
                                yield json.dumps({"error": {"message": "backend non disponibile"}}).encode()
                                return
                            async for chunk in response.aiter_bytes():
                                yield chunk
                except httpx.HTTPError:
                    yield b'{"error":{"message":"backend non disponibile"}}'

        return StreamingResponse(stream_backend(), media_type="text/event-stream")

    async with inference_slot:
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{backend_url}/v1/chat/completions",
                    content=body,
                    headers=backend_headers(),
                )
            try:
                content = response.json()
            except ValueError:
                content = {"error": {"message": "risposta backend non valida"}}
            return JSONResponse(content, status_code=response.status_code)
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="backend di inferenza non disponibile")


@app.get("/internal/admin/models")
async def admin_models(x_internal_key: str | None = Header(default=None)) -> JSONResponse:
    require_internal_key(x_internal_key)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                f"{MODEL_MANAGER_URL}/v1/models/status",
                headers={"X-Internal-Key": INTERNAL_KEY},
            )
        payload = response.json()
        if response.status_code == 200:
            registry = read_registry()
            try:
                payload["routing"] = routing_snapshot(registry)
            except RoutingError:
                payload["routing"] = {"mode": "unavailable", "auto_enabled": False}
            payload["catalog"] = {
                model_id: {
                    key: spec.get(key)
                    for key in ("label", "status", "catalog_state", "capabilities", "purpose", "available", "local_reason")
                    if key in spec
                }
                for model_id, spec in registry.get("models", {}).items()
                if spec.get("catalog_state") in {"qualified_local", "candidate_local"}
            }
        return JSONResponse(payload, status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="controller modelli non disponibile")


@app.post("/internal/admin/routing/simulate")
async def admin_routing_simulate(
    request: Request, x_internal_key: str | None = Header(default=None)
) -> JSONResponse:
    require_internal_key(x_internal_key)
    body = await request.body()
    if len(body) > 32768:
        raise HTTPException(status_code=413, detail="piano troppo grande")
    try:
        payload = json.loads(body)
        result = plan_workflow(
            read_registry(),
            str(payload.get("profile", "auto")),
            payload.get("tasks"),
            active_model=active_backend()[0],
            allow_remote=bool(payload.get("allow_remote", False)),
        )
    except (ValueError, TypeError, RoutingError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse(result)


@app.post("/internal/admin/models/switch")
async def admin_model_switch(
    request: Request, x_internal_key: str | None = Header(default=None)
) -> JSONResponse:
    require_internal_key(x_internal_key)
    body = await request.body()
    if len(body) > 4096:
        raise HTTPException(status_code=413, detail="richiesta troppo grande")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="JSON non valido")
    model_id = str(payload.get("model_id", ""))
    if model_id not in MODEL_ENDPOINTS:
        raise HTTPException(status_code=400, detail="modello sconosciuto")
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{MODEL_MANAGER_URL}/v1/models/switch",
                json={"model_id": model_id},
                headers={"X-Internal-Key": INTERNAL_KEY},
            )
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="cambio modello non disponibile")


@app.post("/internal/v1/ocr/extract")
async def internal_ocr_extract(
    request: Request, x_internal_key: str | None = Header(default=None)
) -> JSONResponse:
    """Run hidden GLM-OCR only while the caller holds the portal FIFO slot."""
    require_internal_key(x_internal_key)
    body = await request.body()
    if len(body) > MAX_OCR_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="richiesta OCR oltre il limite")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON OCR non valido")
    if set(payload) != {"image_base64", "image_sha256"}:
        raise HTTPException(status_code=400, detail="campi OCR non validi")
    if inference_slot.locked():
        raise HTTPException(status_code=429, detail="motore OCR occupato")
    async with inference_slot:
        await release_idle_graphics_for_ocr()
        try:
            async with httpx.AsyncClient(timeout=1220.0) as client:
                response = await client.post(
                    f"{MODEL_MANAGER_URL}/v1/internal/ocr/extract",
                    content=body,
                    headers={"X-Internal-Key": INTERNAL_KEY, "Content-Type": "application/json"},
                )
            try:
                content = response.json()
            except ValueError:
                content = {"detail": "risposta OCR interna non valida"}
            return JSONResponse(content, status_code=response.status_code)
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="motore OCR interno non disponibile")
