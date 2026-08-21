#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s;]+)")


def requirement_files() -> list[Path]:
    roots = [ROOT / "components", ROOT / "services", ROOT / "clients"]
    return sorted(
        path for base in roots for path in base.rglob("requirements*")
        if path.is_file() and "__pycache__" not in path.parts
    )


def created() -> str:
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build() -> dict[str, object]:
    licenses = json.loads((ROOT / "config/dependency-licenses.json").read_text(encoding="utf-8"))
    found: dict[tuple[str, str], dict[str, object]] = {}
    for path in requirement_files():
        relative = path.relative_to(ROOT).as_posix()
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "-r ")):
                continue
            match = PIN.match(line)
            if not match:
                raise ValueError(f"dependency is not exactly pinned: {relative}: {line}")
            name, version = match.groups()
            normalized = name.lower().replace("_", "-")
            if normalized not in licenses:
                raise ValueError(f"missing license record: {normalized}")
            item = found.setdefault((normalized, version), {
                "type": "library", "name": normalized, "version": version,
                "bom-ref": f"pkg:pypi/{normalized}@{version}",
                "purl": f"pkg:pypi/{normalized}@{version}",
                "licenses": [{"expression": licenses[normalized]["license"]}],
                "externalReferences": [{"type": "vcs", "url": licenses[normalized]["source"]}],
                "properties": [], "hashes": [],
            })
            item["properties"].append({"name": "r740:declared-in", "value": relative})
            for value in re.findall(r"--hash=sha256:([0-9a-f]{64})", line):
                record = {"alg": "SHA-256", "content": value}
                if record not in item["hashes"]:
                    item["hashes"].append(record)
    components = []
    for item in found.values():
        item["properties"] = sorted(item["properties"], key=lambda prop: prop["value"])
        if not item["hashes"]:
            item.pop("hashes")
        components.append(item)
    components.sort(key=lambda item: (item["name"], item["version"]))
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.6", "serialNumber": "urn:uuid:00000000-0000-4000-8000-000000000740",
        "version": 1, "metadata": {"timestamp": created(), "component": {"type": "application", "name": "r740-ai-factory-community", "version": "0.2.0"}},
        "components": components,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
