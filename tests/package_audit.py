#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_TEXT = (
    "indomito.ddnsfree.com",
    "Password123Password",
    "Password1234Password",
    "10.77.",
    "192.168.",
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
IGNORED_PARTS = {"__pycache__", ".pytest_cache"}


def source_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.resolve() != Path(__file__).resolve()
        and not any(part in IGNORED_PARTS for part in path.parts)
    ]


def main() -> None:
    files = source_files()
    assert files
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in FORBIDDEN_TEXT:
            assert marker not in text, f"deployment-specific marker in {path}: {marker}"
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(text), f"probable secret in {path}"

    assert not (ROOT / "secrets/admin_token").exists()
    assert not (ROOT / "config/runtime.env").exists()
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "config/runtime.env" in gitignore and "secrets/*" in gitignore

    catalog = json.loads((ROOT / "model-manifests/catalog.json").read_text())
    for model in catalog["models"]:
        assert model["enabled"] is False
        assert model["revision"] is None
        assert model["artifact"] is None
        assert model["sha256"] is None

    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "file: ./secrets/admin_token" in compose
    assert "profiles: [\"cpu\"]" in compose
    assert "profiles: [\"nvidia\"]" in compose
    assert "cap_drop:" in compose and "no-new-privileges:true" in compose
    print(f"PASS package audit ({len(files)} files, no embedded deployment secrets)")


if __name__ == "__main__":
    main()
