#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import json
import hashlib
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
IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", "build", "dist"}


def source_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.resolve() != Path(__file__).resolve()
        and not any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in path.parts)
    ]


def main() -> None:
    files = source_files()
    assert files
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise AssertionError(f"unreviewed binary artifact in source package: {path}") from error
        for marker in FORBIDDEN_TEXT:
            assert marker not in text, f"deployment-specific marker in {path}: {marker}"
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(text), f"probable secret in {path}"

    assert not (ROOT / "secrets/admin_token").exists()
    assert not (ROOT / "config/runtime.env").exists()
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "config/runtime.env" in gitignore and "config/portal.env" in gitignore and "secrets/*" in gitignore
    assert "build/" in gitignore and "dist/" in gitignore and "*.egg-info/" in gitignore

    assert (ROOT / "COPYING").is_file()
    assert (ROOT / "COPYING.LESSER").is_file()
    assert "LGPL-3.0-or-later" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    for path in files:
        if path.name in {"COPYING", "COPYING.LESSER"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert "LGPL-3.0-only" not in text, f"stale license policy in {path}"

    catalog = json.loads((ROOT / "model-manifests/catalog.json").read_text())
    for model in catalog["models"]:
        assert model["enabled"] is False
        assert model["revision"] is None
        assert model["artifact"] is None
        assert model["sha256"] is None

    provenance = json.loads((ROOT / "docs/SOURCE_PROVENANCE.json").read_text())
    assert provenance["production_values_included"] is False
    assert len(provenance["components"]) >= 17
    for component in provenance["components"]:
        assert re.fullmatch(r"[0-9a-f]{64}", component["sha256"])
        assert component["import_status"] != "integrated"

    services_provenance = json.loads(
        (ROOT / "docs/SERVICES_PROVENANCE.json").read_text(encoding="utf-8")
    )
    assert services_provenance["production_values_included"] is False
    assert len(services_provenance["files"]) >= 13
    for component in services_provenance["files"]:
        relative = component["path"]
        if relative.startswith("clients/local-mcp/"):
            candidate = ROOT / relative
        else:
            candidate = ROOT / "services" / relative
        assert candidate.is_file() and not candidate.is_symlink()
        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        assert actual == component["sanitized_sha256"], f"service drift: {candidate}"

    core_provenance = json.loads(
        (ROOT / "components/core/SOURCE-MANIFEST.json").read_text(encoding="utf-8")
    )
    assert core_provenance["contains_secrets"] is False
    for component in core_provenance["source_to_candidate"]:
        assert component["source"] == "private-authoritative-source"
        candidate = ROOT / "components/core" / component["candidate"]
        assert candidate.is_file() and not candidate.is_symlink()
        assert hashlib.sha256(candidate.read_bytes()).hexdigest() == component["candidate_sha256"]
    for relative, expected_hash in core_provenance["new_portability_files"].items():
        candidate = ROOT / "components/core" / relative
        assert candidate.is_file() and not candidate.is_symlink()
        assert hashlib.sha256(candidate.read_bytes()).hexdigest() == expected_hash

    portal_provenance = json.loads(
        (ROOT / "components/portal/SOURCE_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert portal_provenance["authoritative_inventory"] == "hash-only private inventory"
    for component in portal_provenance["entries"]:
        assert component["source"] == "private-authoritative-source"
        candidate = ROOT / "components/portal" / component["candidate"]
        assert candidate.is_file() and not candidate.is_symlink()
        assert hashlib.sha256(candidate.read_bytes()).hexdigest() == component["candidate_sha256"]
    for component in portal_provenance["new_files"]:
        candidate = ROOT / "components/portal" / component["candidate"]
        assert candidate.is_file() and not candidate.is_symlink()
        assert hashlib.sha256(candidate.read_bytes()).hexdigest() == component["candidate_sha256"]

    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "file: ./secrets/admin_token" in compose
    assert "profiles: [\"cpu\"]" in compose
    assert "profiles: [\"nvidia\"]" in compose
    assert "cap_drop:" in compose and "no-new-privileges:true" in compose
    assert "R740_CONTAINER_UID" in compose and "./data/portal:/var/lib/r740-ai-portal" in compose
    print(f"PASS package audit ({len(files)} files, no embedded deployment secrets)")


if __name__ == "__main__":
    main()
