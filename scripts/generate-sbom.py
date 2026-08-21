#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Generate a deterministic SPDX 2.3 source SBOM without external tooling."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", "dist", "build"}
IGNORED_PREFIXES = {"config/runtime.env", "secrets/admin_token"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def source_files(output: Path | None) -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in path.parts):
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative in IGNORED_PREFIXES or (output and path.resolve() == output.resolve()):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())


def created_time() -> str:
    raw = os.environ.get("SOURCE_DATE_EPOCH", "0")
    try:
        epoch = int(raw)
    except ValueError as error:
        raise SystemExit("SOURCE_DATE_EPOCH must be an integer") from error
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(output: Path | None) -> dict[str, object]:
    records = []
    for index, path in enumerate(source_files(output), start=1):
        relative = path.relative_to(ROOT).as_posix()
        records.append(
            {
                "SPDXID": f"SPDXRef-File-{index}",
                "fileName": f"./{relative}",
                "checksums": [{"algorithm": "SHA256", "checksumValue": digest(path)}],
                "licenseConcluded": "NOASSERTION",
                "copyrightText": "NOASSERTION",
            }
        )
    content_fingerprint = hashlib.sha256(
        "\n".join(
            f"{item['fileName']}:{item['checksums'][0]['checksumValue']}" for item in records
        ).encode("utf-8")
    ).hexdigest()
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "r740-ai-factory-community-source",
        "documentNamespace": f"https://example.invalid/r740-ai-factory/sbom/{content_fingerprint}",
        "creationInfo": {
            "created": created_time(),
            "creators": ["Tool: scripts/generate-sbom.py"],
            "licenseListVersion": "3.25",
        },
        "packages": [
            {
                "SPDXID": "SPDXRef-Package",
                "name": "r740-ai-factory-community",
                "versionInfo": "0.2.0",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": True,
                "licenseConcluded": "LGPL-3.0-or-later",
                "licenseDeclared": "LGPL-3.0-or-later",
                "copyrightText": "NOASSERTION",
                "packageVerificationCode": {"packageVerificationCodeValue": content_fingerprint},
            }
        ],
        "files": records,
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-Package",
            },
            *[
                {
                    "spdxElementId": "SPDXRef-Package",
                    "relationshipType": "CONTAINS",
                    "relatedSpdxElement": item["SPDXID"],
                }
                for item in records
            ],
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(build(args.output), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
