#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    installer = (ROOT / "scripts/install-core-systemd.sh").read_text(encoding="utf-8")
    unit = (ROOT / "systemd/r740-ai-core.service.in").read_text(encoding="utf-8")
    assert '"$(id -u)" -ne 0' in installer
    assert "sys.version_info >= (3,11)" in installer
    assert "--no-index --find-links" in installer
    assert "assert not settings.execution_enabled" in installer
    assert "shlex.split(value, posix=True)" in installer
    assert not any(line.strip().startswith("systemctl enable") for line in installer.splitlines())
    for service in ("gateway", "orchestrator", "model-manager", "graphics-manager", "autorouting"):
        assert f"r740-ai-{service}.service" in installer
    for guard in ("NoNewPrivileges=true", "ProtectSystem=strict", "ProtectHome=true"):
        assert guard in unit
    assert "--host 127.0.0.1" in unit
    assert "@CAPS@" in unit
    print("PASS core systemd installer contract")


if __name__ == "__main__":
    main()
