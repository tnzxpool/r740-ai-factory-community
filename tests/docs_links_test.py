#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def main() -> None:
    checked = 0
    for document in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        for target in LINK.findall(document.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            clean = target.split("#", 1)[0]
            resolved = (document.parent / clean).resolve()
            assert resolved.is_relative_to(ROOT.resolve()), f"link escapes repository: {document}: {target}"
            assert resolved.exists(), f"broken link: {document}: {target}"
            checked += 1
    assert checked >= 5
    print(f"PASS documentation links ({checked} local targets)")


if __name__ == "__main__": main()
