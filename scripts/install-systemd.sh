#!/bin/sh
# SPDX-License-Identifier: LGPL-3.0-or-later
set -eu

if [ "$(id -u)" -ne 0 ]; then
  printf '%s\n' "Run this installer as root." >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
INSTALL_DIR=${R740_INSTALL_DIR:-/opt/r740-ai-factory}
CONFIG_DIR=${R740_CONFIG_DIR:-/etc/r740-ai-factory}
STATE_DIR=${R740_STATE_DIR:-/var/lib/r740-ai-factory}
SERVICE_USER=${R740_SERVICE_USER:-r740-ai}

if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' "python3 >= 3.10 is required." >&2
  exit 1
fi
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' || {
  printf '%s\n' "python3 >= 3.10 is required." >&2; exit 1;
}
command -v systemctl >/dev/null 2>&1 || { printf '%s\n' "systemd is required." >&2; exit 1; }

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -m 0755 "$INSTALL_DIR" "$INSTALL_DIR/src" "$INSTALL_DIR/model-manifests"
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$STATE_DIR"
install -d -m 0750 -o root -g "$SERVICE_USER" "$CONFIG_DIR" "$CONFIG_DIR/secrets"
cp -R "$SOURCE_DIR/src/." "$INSTALL_DIR/src/"
# Preserve the operator catalog across upgrades. It may contain locally
# registered models that are intentionally absent from the source tree.
if [ ! -e "$INSTALL_DIR/model-manifests/catalog.json" ]; then
  cp "$SOURCE_DIR/model-manifests/catalog.json" "$INSTALL_DIR/model-manifests/catalog.json"
fi
for source in "$SOURCE_DIR"/model-manifests/*; do
  [ -f "$source" ] || continue
  [ "$(basename "$source")" = catalog.json ] && continue
  cp "$source" "$INSTALL_DIR/model-manifests/"
done

if [ ! -e "$CONFIG_DIR/runtime.env" ]; then
  sed \
    -e "s|^R740_DATA_DIR=.*|R740_DATA_DIR=$STATE_DIR|" \
    -e "s|^R740_MODEL_CATALOG=.*|R740_MODEL_CATALOG=$INSTALL_DIR/model-manifests/catalog.json|" \
    -e "s|^R740_ADMIN_TOKEN_FILE=.*|R740_ADMIN_TOKEN_FILE=$CONFIG_DIR/secrets/admin_token|" \
    "$SOURCE_DIR/config/runtime.env.example" > "$CONFIG_DIR/runtime.env"
fi
chmod 0640 "$CONFIG_DIR/runtime.env"
chown root:"$SERVICE_USER" "$CONFIG_DIR/runtime.env"

R740_CONFIG_DIR="$CONFIG_DIR" \
R740_SECRET_DIR="$CONFIG_DIR/secrets" \
R740_DATA_DIR="$STATE_DIR" \
R740_MODEL_DIR="$STATE_DIR/models" \
R740_CREATE_PORTAL_CONFIG=0 \
  "$SOURCE_DIR/scripts/first-run.sh"
chown root:"$SERVICE_USER" "$CONFIG_DIR/secrets/admin_token"
chmod 0640 "$CONFIG_DIR/secrets/admin_token"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$STATE_DIR"

sed \
  -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
  -e "s|@CONFIG_DIR@|$CONFIG_DIR|g" \
  -e "s|@SERVICE_USER@|$SERVICE_USER|g" \
  -e "s|@STATE_DIR@|$STATE_DIR|g" \
  "$SOURCE_DIR/systemd/r740-ai-factory.service.in" \
  > /etc/systemd/system/r740-ai-factory.service

PYTHONPATH="$INSTALL_DIR/src" \
R740_MODEL_CATALOG="$INSTALL_DIR/model-manifests/catalog.json" \
R740_ADMIN_TOKEN_FILE="$CONFIG_DIR/secrets/admin_token" \
  python3 -m r740_factory.app --check-config

systemctl daemon-reload
printf '%s\n' "Installed. Enable with: systemctl enable --now r740-ai-factory"
