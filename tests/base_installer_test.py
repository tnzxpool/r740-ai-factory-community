#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    install = (ROOT / "scripts/install-systemd.sh").read_text(encoding="utf-8")
    first = (ROOT / "scripts/first-run.sh").read_text(encoding="utf-8")
    uninstall = (ROOT / "scripts/uninstall-systemd.sh").read_text(encoding="utf-8")
    preflight = (ROOT / "scripts/preflight.sh").read_text(encoding="utf-8")
    assert "sys.version_info >= (3,10)" in install and "systemd is required" in install
    assert "R740_CREATE_PORTAL_CONFIG=0" in install
    assert 'if [ ! -e "$INSTALL_DIR/model-manifests/catalog.json" ]' in install
    assert '[ "$(basename "$source")" = catalog.json ] && continue' in install
    assert "CREATE_PORTAL_CONFIG" in first
    assert not any(line.strip().startswith("systemctl enable") for line in install.splitlines())
    for unit in ("r740-ai-factory", "r740-ai-portal", "r740-ai-gateway", "r740-ai-model-manager"):
        assert unit in uninstall
    assert "/etc/systemd/system/r740-model-*.service" in uninstall
    for mode in ("compose-cpu", "compose-nvidia", "compose-portal", "systemd-control", "systemd-core", "systemd-model"):
        assert mode in preflight
    assert "NVIDIA Container Toolkit" in preflight and "/run/systemd/system" in preflight
    doctor = (ROOT / "scripts/doctor.sh").read_text(encoding="utf-8")
    assert "factory-(cpu|nvidia)" in doctor and 'fail "control plane not reachable' in doctor
    print("PASS base install, preflight and complete uninstall contracts")


if __name__ == "__main__": main()
