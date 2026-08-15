#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path


def create_secret(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.stat().st_size < 32:
            raise RuntimeError(f"existing secret is too short: {path}")
        return False
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(secrets.token_urlsafe(48) + "\n")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate auxiliary service secrets locally")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    for name in (
        "parser.key", "tools.token", "sandbox.token",
        "orchestrator.key", "backend.key", "portal-core.key",
    ):
        target = args.directory / name
        action = "created" if create_secret(target) else "kept"
        print(f"{action}: {target}")
    print("Secret values were not printed.")


if __name__ == "__main__":
    main()
