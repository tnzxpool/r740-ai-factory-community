#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-source-import.py"
MANIFEST = ROOT / "docs" / "SOURCE_PROVENANCE.json"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    first = manifest["components"][0]
    key = f"{first['group']}/{first['file']}"

    empty = run("--json")
    assert empty.returncode == 0
    empty_report = json.loads(empty.stdout)
    assert empty_report["status"] == "PASS"
    assert empty_report["paths_recorded"] is False

    unknown = run("--source", "core/not-listed.py=C:/missing")
    assert unknown.returncode != 0

    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / "candidate.py"
        candidate.write_text("not the authoritative source", encoding="utf-8")
        mismatch = run("--source", f"{key}={candidate}", "--json")
        assert mismatch.returncode == 1
        report = json.loads(mismatch.stdout)
        assert report["results"][0]["sha256_match"] is False
        assert str(candidate) not in mismatch.stdout

        candidate.write_text("sk-" + "A" * 30, encoding="utf-8")
        sensitive = run("--source", f"{key}={candidate}", "--json")
        assert sensitive.returncode == 1
        report = json.loads(sensitive.stdout)
        assert report["results"][0]["sensitive_pattern_count"] == 1

    print("PASS source import verifier")


if __name__ == "__main__":
    main()
