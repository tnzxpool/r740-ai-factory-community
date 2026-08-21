#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0)); return int(stream.getsockname()[1])


def main() -> None:
    backend_port, app_port = free_port(), free_port()
    with tempfile.TemporaryDirectory(prefix="r740-install-e2e-") as directory:
        temp = Path(directory); token = temp / "admin_token"
        token.write_text("install-e2e-" + "x" * 40, encoding="utf-8")
        backend_key = temp / "backend_api_key"; backend_key.write_text("backend-test-key", encoding="utf-8")
        backend = subprocess.Popen([sys.executable, str(ROOT / "tests/fake_openai_backend.py"), "--port", str(backend_port), "--require-bearer", "backend-test-key"])
        env = os.environ.copy(); env.update({
            "PYTHONPATH": str(ROOT / "src"), "R740_BIND": "127.0.0.1", "R740_PORT": str(app_port),
            "R740_DATA_DIR": str(temp / "data"), "R740_MODEL_CATALOG": str(ROOT / "model-manifests/catalog.json"),
            "R740_ADMIN_TOKEN_FILE": str(token), "R740_HARDWARE_PROFILE": "cpu",
            "R740_INFERENCE_BASE_URL": f"http://127.0.0.1:{backend_port}",
            "R740_INFERENCE_API_KEY_FILE": str(backend_key),
        })
        app = subprocess.Popen([sys.executable, "-m", "r740_factory.app"], env=env)
        try:
            time.sleep(0.3)
            verify = subprocess.run([
                sys.executable, str(ROOT / "scripts/verify-install.py"), "--url", f"http://127.0.0.1:{app_port}",
                "--token-file", str(token), "--expect-inference", "--model", "local-model",
            ], text=True, capture_output=True, timeout=20)
            assert verify.returncode == 0, verify.stderr + verify.stdout
            assert "PASS installation" in verify.stdout
        finally:
            for process in (app, backend):
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
    print("PASS clean install journey with authenticated visible response")


if __name__ == "__main__": main()
