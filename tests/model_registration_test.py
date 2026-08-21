#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if os.name == "nt":
        print("SKIP model registration renderer requires POSIX artifact paths"); return
    with tempfile.TemporaryDirectory(prefix="r740-register-") as directory:
        root = Path(directory); runtime = root / "llama-server"; model = root / "model.gguf"; output = root / "output"
        runtime.write_bytes(b"#!/bin/sh\nexit 0\n"); runtime.chmod(0o755); model.write_bytes(b"GGUF-community-test")
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts/register-local-model.py"), "--model", str(model), "--runtime", str(runtime),
            "--id", "local-model", "--display-name", "Local test", "--license", "Apache-2.0",
            "--upstream-repo", "example/model", "--revision", "0" * 40, "--output-dir", str(output),
        ], text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        manifest = json.loads((output / "model.json").read_text())
        assert manifest["model_sha256"] == hashlib.sha256(model.read_bytes()).hexdigest()
        unit = (output / "r740-model-community.service").read_text()
        assert "--host 127.0.0.1" in unit and str(model) in unit
        assert "0.0.0.0" not in unit and "WantedBy=multi-user.target" in unit
        checksums = (output / "local-model.sha256").read_text()
        assert hashlib.sha256(runtime.read_bytes()).hexdigest() in checksums
        assert hashlib.sha256(model.read_bytes()).hexdigest() in checksums
        assert "ExecStartPre=/usr/bin/sha256sum --check --status" in unit
    print("PASS local model registration prepare-only flow")


if __name__ == "__main__": main()
