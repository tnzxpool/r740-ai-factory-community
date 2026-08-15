#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate-sbom.py"


def generate(output: Path) -> bytes:
    environment = dict(os.environ, SOURCE_DATE_EPOCH="0")
    subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    return output.read_bytes()


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        first_path = Path(directory) / "first.json"
        second_path = Path(directory) / "second.json"
        first = generate(first_path)
        second = generate(second_path)
        assert first == second
        payload = json.loads(first)
        assert payload["spdxVersion"] == "SPDX-2.3"
        assert payload["packages"][0]["licenseDeclared"] == "LGPL-3.0-or-later"
        names = {item["fileName"] for item in payload["files"]}
        assert "./secrets/admin_token" not in names
        assert "./config/runtime.env" not in names
        assert "./src/r740_factory/app.py" in names
    print("PASS deterministic SPDX source SBOM")


if __name__ == "__main__":
    main()
