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


def get(url: str, key: str | None = None):
    headers = {"X-AI-Parser-Key": key} if key else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=2) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="parser-smoke-") as tmp:
        base = Path(tmp)
        key = "parser-smoke-" + "x" * 32
        key_path = base / "internal.key"
        key_path.write_text(key, encoding="ascii")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = os.environ.copy()
        env.update({
            "AI_PARSER_HOST": "127.0.0.1",
            "AI_PARSER_PORT": str(port),
            "AI_PARSER_ALLOWED_IPS": "127.0.0.1",
            "AI_PARSER_KEY_FILE": str(key_path),
            "AI_PARSER_TEMP_DIR": str(base / "tmp"),
        })
        process = subprocess.Popen([sys.executable, str(ROOT / "src/parser_gateway.py")], env=env)
        try:
            deadline = time.monotonic() + 8
            while True:
                try:
                    status, _ = get(f"http://127.0.0.1:{port}/health")
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
            assert status == 403
            status, payload = get(f"http://127.0.0.1:{port}/health", key)
            assert status == 200 and payload["status"] == "ok"
            status, _ = get(f"http://127.0.0.1:{port}/other", key)
            assert status == 404
        finally:
            process.terminate()
            process.wait(timeout=5)
    print("PASS parser auth/health smoke")


if __name__ == "__main__":
    main()

