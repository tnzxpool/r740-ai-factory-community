#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    installer = (ROOT / "scripts/install-portal-systemd.sh").read_text(encoding="utf-8")
    unit = (ROOT / "systemd/r740-ai-portal.service.in").read_text(encoding="utf-8")
    assert '"$(id -u)" -ne 0' in installer
    assert "--no-index --find-links" in installer
    assert 'portal_config_new=0' in installer and 'if [ "$portal_config_new" -eq 1 ]' in installer
    assert "systemctl enable --now" in installer
    assert not any(line.strip().startswith("systemctl enable") for line in installer.splitlines())
    assert "curl " not in installer and "wget " not in installer
    assert "--host 127.0.0.1" in unit
    for guard in ("NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true"):
        assert guard in unit
    assert "@VENV_DIR@/bin/python" in unit
    print("PASS portal systemd installer contract")


if __name__ == "__main__":
    main()
