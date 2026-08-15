# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


class InferenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenAICompatibleAdapter:
    base_url: str
    timeout_seconds: int

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def chat(self, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        if not self.configured:
            raise InferenceError("inference backend is not configured")
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
                return response.status, body
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                detail = {"error": "backend request failed"}
            return exc.code, detail
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise InferenceError(f"inference backend unavailable: {type(exc).__name__}") from exc
