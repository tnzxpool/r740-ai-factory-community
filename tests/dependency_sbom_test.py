#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dependency_sbom", ROOT / "scripts/generate-dependency-sbom.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def main() -> None:
    first = module.build(); second = module.build()
    assert first == second and first["specVersion"] == "1.6"
    components = first["components"]
    assert len(components) >= 19
    assert all(item["licenses"][0]["expression"] for item in components)
    versions = {(item["name"], item["version"]) for item in components}
    assert ("fastapi", "0.116.1") in versions and ("fastapi", "0.92.0") in versions
    assert any(item["name"] == "cryptography" and item.get("hashes") for item in components)
    print(f"PASS dependency CycloneDX SBOM ({len(components)} pinned components)")


if __name__ == "__main__":
    main()
