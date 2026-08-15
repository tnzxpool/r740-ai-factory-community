#!/bin/sh
# SPDX-License-Identifier: LGPL-3.0-or-later
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer as root." >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
INSTALL_DIR=${R740_INSTALL_DIR:-/opt/r740-ai-factory}
CONFIG_DIR=${R740_CONFIG_DIR:-/etc/r740-ai-factory}
STATE_DIR=${R740_STATE_DIR:-/var/lib/r740-ai-factory}
SERVICE_USER=${R740_SERVICE_USER:-r740-ai}
PORT=${R740_PORTAL_PORT:-8081}
VENV_DIR=${R740_PORTAL_VENV:-$INSTALL_DIR/venv-portal}
WHEELHOUSE=${R740_WHEELHOUSE:-}

case "$PORT" in
  *[!0-9]*|'') echo "R740_PORTAL_PORT must be numeric" >&2; exit 1 ;;
esac
if [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
  echo "R740_PORTAL_PORT must be between 1024 and 65535" >&2
  exit 1
fi
command -v python3 >/dev/null 2>&1 || { echo "python3 >= 3.11 is required" >&2; exit 1; }

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -m 0755 "$INSTALL_DIR/components/portal"
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$STATE_DIR" "$STATE_DIR/portal"
install -d -m 0750 -o root -g "$SERVICE_USER" "$CONFIG_DIR" "$CONFIG_DIR/secrets"
cp -R "$SOURCE_DIR/components/portal/src" "$SOURCE_DIR/components/portal/pyproject.toml" \
  "$SOURCE_DIR/components/portal/requirements.txt" "$INSTALL_DIR/components/portal/"

python3 -m venv "$VENV_DIR"
if [ -n "$WHEELHOUSE" ]; then
  [ -d "$WHEELHOUSE" ] || { echo "R740_WHEELHOUSE is not a directory" >&2; exit 1; }
  "$VENV_DIR/bin/pip" install --no-index --find-links "$WHEELHOUSE" "$INSTALL_DIR/components/portal"
else
  "$VENV_DIR/bin/pip" install "$INSTALL_DIR/components/portal"
fi

portal_config_new=0
if [ ! -e "$CONFIG_DIR/portal.env" ]; then
  portal_config_new=1
fi
R740_CONFIG_DIR="$CONFIG_DIR" R740_SECRET_DIR="$CONFIG_DIR/secrets" \
R740_DATA_DIR="$STATE_DIR" R740_MODEL_DIR="$STATE_DIR/models" \
  "$SOURCE_DIR/scripts/first-run.sh"

if [ "$portal_config_new" -eq 1 ]; then
  sed \
    -e "s|^AI_PORTAL_DB=.*|AI_PORTAL_DB=$STATE_DIR/portal/portal.db|" \
    -e "s|^AI_SETUP_TOKEN_FILE=.*|AI_SETUP_TOKEN_FILE=$CONFIG_DIR/secrets/setup_token|" \
    -e "s|^AI_PARSER_KEY_FILE=.*|AI_PARSER_KEY_FILE=$CONFIG_DIR/secrets/parser.key|" \
    -e "s|^AI_TOOLS_TOKEN_FILE=.*|AI_TOOLS_TOKEN_FILE=$CONFIG_DIR/secrets/tools.token|" \
    -e "s|^AI_SANDBOX_TOKEN_FILE=.*|AI_SANDBOX_TOKEN_FILE=$CONFIG_DIR/secrets/sandbox.token|" \
    -e "s|^AI_LOCAL_MCP_POLICY_KEY_FILE=.*|AI_LOCAL_MCP_POLICY_KEY_FILE=$CONFIG_DIR/secrets/local-mcp-policy-signing.key|" \
    "$CONFIG_DIR/portal.env" > "$CONFIG_DIR/portal.env.new"
  mv "$CONFIG_DIR/portal.env.new" "$CONFIG_DIR/portal.env"
fi
chmod 0640 "$CONFIG_DIR/portal.env" "$CONFIG_DIR/secrets/setup_token"
chown root:"$SERVICE_USER" "$CONFIG_DIR/portal.env" "$CONFIG_DIR/secrets/setup_token"
chown -R root:root "$INSTALL_DIR/components/portal" "$VENV_DIR"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$STATE_DIR/portal"

sed \
  -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
  -e "s|@CONFIG_DIR@|$CONFIG_DIR|g" \
  -e "s|@STATE_DIR@|$STATE_DIR|g" \
  -e "s|@SERVICE_USER@|$SERVICE_USER|g" \
  -e "s|@VENV_DIR@|$VENV_DIR|g" \
  -e "s|@PORT@|$PORT|g" \
  "$SOURCE_DIR/systemd/r740-ai-portal.service.in" > /etc/systemd/system/r740-ai-portal.service

set -a
. "$CONFIG_DIR/portal.env"
set +a
PYTHONPATH="$INSTALL_DIR/components/portal/src" "$VENV_DIR/bin/python" -c \
  "from r740_portal.portal import app; assert app.title == 'R740 AI Portal'"

systemctl daemon-reload
echo "Portal installed but not started."
echo "Inspect the local setup token, then run: systemctl enable --now r740-ai-portal"
