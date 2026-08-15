#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(url: str, *, token: str | None = None, body: object | None = None):
    headers = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main() -> None:
    catalog = json.loads((ROOT / "model-manifests/catalog.json").read_text())
    assert catalog["schema_version"] == 1
    assert catalog["models"] and all(not item["enabled"] for item in catalog["models"])
    assert all(item["sha256"] is None for item in catalog["models"])

    with tempfile.TemporaryDirectory(prefix="r740-smoke-") as tmp:
        temp = Path(tmp)
        token = "smoke-test-token-" + "x" * 32
        token_file = temp / "admin_token"
        token_file.write_text(token + "\n", encoding="utf-8")
        port = free_port()
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(ROOT / "src"),
                "R740_BIND": "127.0.0.1",
                "R740_PORT": str(port),
                "R740_DATA_DIR": str(temp / "data"),
                "R740_MODEL_CATALOG": str(ROOT / "model-manifests/catalog.json"),
                "R740_ADMIN_TOKEN_FILE": str(token_file),
                "R740_HARDWARE_PROFILE": "cpu",
                "R740_INFERENCE_BASE_URL": "",
            }
        )
        process = subprocess.Popen(
            [sys.executable, "-m", "r740_factory.app"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 10
            while True:
                try:
                    status, health = request(base + "/healthz")
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise AssertionError("server did not become ready")
                    time.sleep(0.05)
            assert status == 200 and health["status"] == "ok"
            status, hardware = request(base + "/api/v1/hardware")
            assert status == 200 and hardware["active_profile"] == "cpu"
            status, models = request(base + "/api/v1/models")
            assert status == 200 and models["schema_version"] == 1
            status, _ = request(
                base + "/api/v1/chat/completions", body={"messages": []}
            )
            assert status == 401
            status, unavailable = request(
                base + "/api/v1/chat/completions",
                token=token,
                body={"messages": []},
            )
            assert status == 503 and "not configured" in unavailable["error"]
            status, _ = request(base + "/api/v1/does-not-exist")
            assert status == 404
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.returncode not in {0, -15, 1} and os.name != "nt":
            raise AssertionError(f"unexpected server exit: {process.returncode}")
    print("PASS community installer smoke test")


if __name__ == "__main__":
    main()
