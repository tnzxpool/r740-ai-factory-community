#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Verify private source inputs without copying them into the repository."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = ROOT / "docs" / "SOURCE_PROVENANCE.json"
SENSITIVE = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bhf_[A-Za-z0-9]{20,}\b"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_sources(values: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        key, separator, raw_path = value.partition("=")
        if not separator or "/" not in key or not raw_path:
            raise SystemExit(f"invalid --source {value!r}; expected group/file=/path")
        if key in parsed:
            raise SystemExit(f"duplicate source key: {key}")
        parsed[key] = Path(raw_path).resolve()
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="GROUP/FILE=PATH",
        help="private input to verify; the file is never copied",
    )
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    expected = {
        f"{item['group']}/{item['file']}": item["sha256"]
        for item in manifest["components"]
    }
    sources = parse_sources(args.source)
    unknown = sorted(set(sources) - set(expected))
    if unknown:
        raise SystemExit(f"unknown source keys: {', '.join(unknown)}")
    if args.require_all and set(sources) != set(expected):
        missing = sorted(set(expected) - set(sources))
        raise SystemExit(f"missing source keys: {', '.join(missing)}")

    results: list[dict[str, object]] = []
    failed = False
    for key, path in sorted(sources.items()):
        regular = path.is_file() and not path.is_symlink()
        actual = sha256(path) if regular else None
        hash_ok = actual == expected[key]
        sensitive_hits = 0
        if regular:
            data = path.read_bytes()
            sensitive_hits = sum(bool(pattern.search(data)) for pattern in SENSITIVE)
        ok = regular and hash_ok and sensitive_hits == 0
        failed = failed or not ok
        results.append(
            {
                "component": key,
                "regular_file": regular,
                "sha256_match": hash_ok,
                "sensitive_pattern_count": sensitive_hits,
                "status": "PASS" if ok else "FAIL",
            }
        )

    report = {
        "schema": 1,
        "files_requested": len(sources),
        "paths_recorded": False,
        "content_copied": False,
        "status": "FAIL" if failed else "PASS",
        "results": results,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for result in results:
            print(f"{result['status']} {result['component']}")
        print(f"{report['status']} verified {len(results)} source file(s)")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
