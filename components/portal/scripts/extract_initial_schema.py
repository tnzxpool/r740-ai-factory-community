#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 R740 AI Factory contributors
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Extract the authoritative idempotent initial SQLite schema from portal.py."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "r740_portal" / "portal.py"
OUTPUT = ROOT / "migrations" / "0001_initial.sql"


def main() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    schema = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "executescript" or not node.args:
            continue
        value = node.args[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            candidate = value.value
            if "CREATE TABLE IF NOT EXISTS users" in candidate:
                schema = candidate.strip() + "\n"
                break
    if schema is None:
        raise RuntimeError("authoritative initial schema not found")
    header = (
        "-- SPDX-FileCopyrightText: 2026 R740 AI Factory contributors\n"
        "-- SPDX-License-Identifier: LGPL-3.0-or-later\n"
        "-- Generated from src/r740_portal/portal.py; idempotent fresh-install schema.\n"
    )
    OUTPUT.write_text(header + schema, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

