#!/bin/sh
# SPDX-License-Identifier: LGPL-3.0-or-later
set -eu

if [ "$(id -u)" -ne 0 ]; then
  printf '%s\n' "Run this uninstaller as root." >&2
  exit 1
fi

if [ "${1:-}" != "--yes" ]; then
  printf '%s\n' "Usage: sudo $0 --yes [--purge-data]" >&2
  printf '%s\n' "Configuration and state are preserved unless --purge-data is given." >&2
  exit 2
fi

INSTALL_DIR=${R740_INSTALL_DIR:-/opt/r740-ai-factory}
CONFIG_DIR=${R740_CONFIG_DIR:-/etc/r740-ai-factory}
STATE_DIR=${R740_STATE_DIR:-/var/lib/r740-ai-factory}
PURGE=${2:-}

case "$INSTALL_DIR" in /opt/r740-ai-factory|/opt/r740-ai-factory/*) ;; *)
  printf 'Refusing unsafe install path: %s\n' "$INSTALL_DIR" >&2; exit 3;;
esac
case "$CONFIG_DIR" in /etc/r740-ai-factory|/etc/r740-ai-factory/*) ;; *)
  printf 'Refusing unsafe config path: %s\n' "$CONFIG_DIR" >&2; exit 3;;
esac
case "$STATE_DIR" in /var/lib/r740-ai-factory|/var/lib/r740-ai-factory/*) ;; *)
  printf 'Refusing unsafe state path: %s\n' "$STATE_DIR" >&2; exit 3;;
esac

for unit in \
  r740-ai-factory.service r740-ai-portal.service r740-ai-gateway.service \
  r740-ai-orchestrator.service r740-ai-model-manager.service \
  r740-ai-graphics-manager.service r740-ai-autorouting.service; do
  systemctl disable --now "$unit" 2>/dev/null || true
  rm -f "/etc/systemd/system/$unit"
done
for unit_path in /etc/systemd/system/r740-model-*.service; do
  [ -e "$unit_path" ] || continue
  unit=${unit_path##*/}
  systemctl disable --now "$unit" 2>/dev/null || true
  rm -f "$unit_path"
done
systemctl daemon-reload

if [ -d "$INSTALL_DIR" ]; then
  find "$INSTALL_DIR" -depth -delete
fi

if [ "$PURGE" = "--purge-data" ]; then
  printf '%s\n' "Purging installation-specific configuration and state."
  [ ! -d "$CONFIG_DIR" ] || find "$CONFIG_DIR" -depth -delete
  [ ! -d "$STATE_DIR" ] || find "$STATE_DIR" -depth -delete
else
  printf 'Preserved configuration: %s\n' "$CONFIG_DIR"
  printf 'Preserved state: %s\n' "$STATE_DIR"
fi

printf '%s\n' "R740 AI Factory control plane, portal, core and model units removed."
