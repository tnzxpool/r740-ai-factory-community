#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 R740 AI Factory contributors
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Fail-closed scanner for values forbidden in the Community portal staging."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
TEXT_SUFFIXES = {".py", ".html", ".md", ".txt", ".json", ".sql", ".example"}

forbidden_domain = "indo" + "mito" + "." + "ddns" + "free" + ".com"
old_demo_value = "Password" + "123" + "Password"
private_key_marker = "-----BEGIN " + "PRIVATE KEY-----"

RULES = {
    "production_domain": re.compile(re.escape(forbidden_domain), re.IGNORECASE),
    "known_demo_credential": re.compile(re.escape(old_demo_value)),
    "rfc1918_address": re.compile(
        r"(?<![0-9])(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.(?:\d{1,3}\.)\d{1,3}|"
        r"172\.(?:1[6-9]|2\d|3[01])\.(?:\d{1,3}\.)\d{1,3})(?![0-9])"
    ),
    "live_host_path": re.compile(r"(?i)(?:[A-Z]:\\R740|/root/r740|/var/lib/ai-portal|/opt/ai-|/ai/models)"),
    "private_key": re.compile(re.escape(private_key_marker)),
    "provider_token": re.compile(
        r"(?:hf_[A-Za-z0-9]{24,}|gh[opurs]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})"
    ),
    "url_credentials": re.compile(r"(?i)\bhttps?://[^\s/:]+:[^\s/@]+@"),
}


def main() -> int:
    findings: list[dict[str, object]] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.resolve() == SELF or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for rule, pattern in RULES.items():
                if pattern.search(line):
                    findings.append({
                        "rule": rule,
                        "path": path.relative_to(ROOT).as_posix(),
                        "line": number,
                    })
    print(json.dumps({"values_included": False, "findings": findings}, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

