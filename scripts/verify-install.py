#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Verify a running Community control plane without printing credentials."""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path


def request(url: str, *, token: str = "", payload: object | None = None) -> tuple[int, object]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    call = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(call, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--token-file", type=Path, default=Path("secrets/admin_token"))
    parser.add_argument("--expect-inference", action="store_true")
    parser.add_argument("--model", help="exact model identifier exposed by the backend")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    if args.expect_inference and not args.model:
        parser.error("--expect-inference requires --model")

    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise SystemExit("FAIL token file is missing or too short")

    status, health = request(base + "/healthz")
    assert status == 200 and isinstance(health, dict) and health.get("status") == "ok"
    status, info = request(base + "/api/v1/info")
    assert status == 200 and isinstance(info, dict)
    status, hardware = request(base + "/api/v1/hardware")
    assert status == 200 and isinstance(hardware, dict) and hardware.get("active_profile")
    status, models = request(base + "/api/v1/models")
    assert status == 200 and isinstance(models, dict) and models.get("schema_version") == 1
    payload = {"model": args.model or "not-configured", "messages": [{"role": "user", "content": "Reply with R740-READY"}]}
    status, _ = request(base + "/api/v1/chat/completions", payload=payload)
    assert status == 401, "unauthenticated inference was not rejected"
    status, result = request(base + "/api/v1/chat/completions", token=token, payload=payload)
    if args.expect_inference:
        assert status == 200 and isinstance(result, dict)
        content = result.get("choices", [{}])[0].get("message", {}).get("content")
        assert isinstance(content, str) and content.strip(), "backend returned no visible content"
    else:
        configured = bool(info.get("inference_configured"))
        assert status in ({200, 400, 422} if configured else {503})
    print(f"PASS installation health={health['status']} hardware={hardware['active_profile']} inference={bool(info.get('inference_configured'))}")


if __name__ == "__main__":
    main()
