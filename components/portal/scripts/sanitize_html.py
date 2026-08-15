#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 R740 AI Factory contributors
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Reproducible, value-free transformation of the authoritative HTML copies."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "src" / "r740_portal"
SPDX = (
    "<!-- SPDX-FileCopyrightText: 2026 R740 AI Factory contributors -->\n"
    "<!-- SPDX-License-Identifier: LGPL-3.0-or-later -->\n"
)


def write_if_changed(path: Path, text: str) -> None:
    if path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8", newline="\n")


def ensure_spdx(text: str) -> str:
    return text if "SPDX-License-Identifier:" in text[:300] else SPDX + text


def sanitize_login() -> None:
    path = ROOT / "login.html"
    text = path.read_text(encoding="utf-8")
    replacement = (
        '<div id="demoAccess" class="test-access" role="note" '
        'aria-label="Accesso dimostrativo opzionale" hidden>'
        '<strong>Accesso dimostrativo opzionale</strong>'
        '<span>user: <code id="demoUser"></code></span>'
        '<span>La credenziale viene configurata localmente dall\'operatore e non è distribuita.</span>'
        '</div><form id="form">'
    )
    text, count = re.subn(
        r'<div class="test-access".*?</div><form id="form">', replacement, text, count=1,
    )
    if count != 1 and 'id="demoAccess"' not in text:
        raise RuntimeError("authoritative demo banner did not match")
    hook = """async function loadPublicConfig(){
  try{const r=await fetch('/api/public-config'),d=await r.json(),demo=d.demo_access||{};
    if(r.ok&&demo.enabled&&demo.username){document.getElementById('demoUser').textContent=demo.username;document.getElementById('demoAccess').hidden=false}}
  catch(_){/* fail closed: no demo banner */}
}
loadPublicConfig();
"""
    if "async function loadPublicConfig" not in text:
        text = text.replace("<script>\n", "<script>\n" + hook, 1)
    write_if_changed(path, ensure_spdx(text))


def main() -> None:
    sanitize_login()
    for name in ("change-password.html", "setup.html"):
        path = ROOT / name
        write_if_changed(path, ensure_spdx(path.read_text(encoding="utf-8")))
    setup = ROOT / "setup.html"
    text = setup.read_text(encoding="utf-8").replace(
        "Questa pagina funziona soltanto dalla LAN e una sola volta.",
        "Questa pagina funziona soltanto dalla rete amministrativa configurata e una sola volta.",
    )
    write_if_changed(setup, text)


if __name__ == "__main__":
    main()
