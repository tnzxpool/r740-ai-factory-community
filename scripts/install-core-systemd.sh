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
RUNTIME_DIR=${R740_RUNTIME_DIR:-/run/r740-ai-factory}
SERVICE_USER=${R740_SERVICE_USER:-r740-ai}
VENV_DIR=${R740_CORE_VENV:-$INSTALL_DIR/venv-core}
WHEELHOUSE=${R740_WHEELHOUSE:-}

command -v python3 >/dev/null 2>&1 || { echo "python3 >= 3.11 is required" >&2; exit 1; }
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' || { echo "python3 >= 3.11 is required" >&2; exit 1; }
command -v systemctl >/dev/null 2>&1 || { echo "systemd is required for the GPU controller" >&2; exit 1; }
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -m 0755 "$INSTALL_DIR/components/core"
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" \
  "$STATE_DIR" "$STATE_DIR/registry" "$STATE_DIR/models" "$STATE_DIR/downloads" \
  "$STATE_DIR/results" "$STATE_DIR/metrics"
install -d -m 0750 -o root -g "$SERVICE_USER" "$CONFIG_DIR" "$CONFIG_DIR/secrets"
install -d -m 0770 -o root -g "$SERVICE_USER" "$RUNTIME_DIR"
cp -R "$SOURCE_DIR/components/core/src" "$SOURCE_DIR/components/core/pyproject.toml" \
  "$SOURCE_DIR/components/core/requirements.txt" "$INSTALL_DIR/components/core/"

python3 -m venv "$VENV_DIR"
if [ -n "$WHEELHOUSE" ]; then
  [ -d "$WHEELHOUSE" ] || { echo "R740_WHEELHOUSE is not a directory" >&2; exit 1; }
  "$VENV_DIR/bin/pip" install --no-index --find-links "$WHEELHOUSE" "$INSTALL_DIR/components/core"
else
  "$VENV_DIR/bin/pip" install "$INSTALL_DIR/components/core"
fi

if [ ! -e "$CONFIG_DIR/core.env" ]; then
  sed \
    -e "s|^AI_STATE_DIR=.*|AI_STATE_DIR=$STATE_DIR|" \
    -e "s|^AI_RUNTIME_DIR=.*|AI_RUNTIME_DIR=$RUNTIME_DIR|" \
    -e "s|^AI_MODELS_DIR=.*|AI_MODELS_DIR=$STATE_DIR/models|" \
    -e "s|^AI_DOWNLOADS_DIR=.*|AI_DOWNLOADS_DIR=$STATE_DIR/downloads|" \
    -e "s|^AI_RESULTS_DIR=.*|AI_RESULTS_DIR=$STATE_DIR/results|" \
    -e "s|^AI_METRICS_DIR=.*|AI_METRICS_DIR=$STATE_DIR/metrics|" \
    -e "s|^AI_CAPABILITIES_FILE=.*|AI_CAPABILITIES_FILE=$STATE_DIR/registry/capabilities.json|" \
    -e "s|^AI_MODEL_STATE_FILE=.*|AI_MODEL_STATE_FILE=$STATE_DIR/registry/model_state.json|" \
    -e "s|^AI_GRAPHICS_STATE_FILE=.*|AI_GRAPHICS_STATE_FILE=$STATE_DIR/registry/graphics_state.json|" \
    -e "s|^AI_GPU_LOCK_FILE=.*|AI_GPU_LOCK_FILE=$RUNTIME_DIR/gpu.lock|" \
    -e "s|^AI_WORKFLOW_LOCK_FILE=.*|AI_WORKFLOW_LOCK_FILE=$RUNTIME_DIR/workflow.lock|" \
    -e "s|^AI_ORCHESTRATOR_KEY_FILE=.*|AI_ORCHESTRATOR_KEY_FILE=$CONFIG_DIR/secrets/orchestrator.key|" \
    -e "s|^AI_BACKEND_KEY_FILE=.*|AI_BACKEND_KEY_FILE=$CONFIG_DIR/secrets/backend.key|" \
    -e "s|^AI_PORTAL_CORE_KEY_FILE=.*|AI_PORTAL_CORE_KEY_FILE=$CONFIG_DIR/secrets/portal-core.key|" \
    "$SOURCE_DIR/components/core/config/core.env.example" > "$CONFIG_DIR/core.env"
fi

python3 "$SOURCE_DIR/scripts/generate-service-secrets.py" "$CONFIG_DIR/secrets"
for secret in orchestrator.key backend.key portal-core.key; do
  chmod 0640 "$CONFIG_DIR/secrets/$secret"
  chown root:"$SERVICE_USER" "$CONFIG_DIR/secrets/$secret"
done
chmod 0640 "$CONFIG_DIR/core.env"
chown root:"$SERVICE_USER" "$CONFIG_DIR/core.env"

if [ ! -e "$STATE_DIR/registry/capabilities.json" ]; then
  install -m 0640 -o "$SERVICE_USER" -g "$SERVICE_USER" \
    "$SOURCE_DIR/components/core/config/model-registry.example.json" \
    "$STATE_DIR/registry/capabilities.json"
fi
chown -R root:root "$INSTALL_DIR/components/core" "$VENV_DIR"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$STATE_DIR"

render_unit() {
  unit=$1 description=$2 module=$3 port=$4 user=$5 caps=$6
  sed \
    -e "s|@DESCRIPTION@|$description|g" \
    -e "s|@MODULE@|$module|g" \
    -e "s|@PORT@|$port|g" \
    -e "s|@USER@|$user|g" \
    -e "s|@GROUP@|$SERVICE_USER|g" \
    -e "s|@CAPS@|$caps|g" \
    -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
    -e "s|@CONFIG_DIR@|$CONFIG_DIR|g" \
    -e "s|@STATE_DIR@|$STATE_DIR|g" \
    -e "s|@RUNTIME_DIR@|$RUNTIME_DIR|g" \
    -e "s|@VENV_DIR@|$VENV_DIR|g" \
    "$SOURCE_DIR/systemd/r740-ai-core.service.in" > "/etc/systemd/system/$unit"
}

render_unit r740-ai-gateway.service "gateway" gateway 41138 "$SERVICE_USER" ""
render_unit r740-ai-orchestrator.service "orchestrator" orchestrator 41139 "$SERVICE_USER" ""
render_unit r740-ai-model-manager.service "model manager" model_manager 41146 root "CAP_CHOWN CAP_DAC_OVERRIDE CAP_FOWNER"
render_unit r740-ai-graphics-manager.service "graphics manager" graphics_manager 41148 root "CAP_CHOWN CAP_DAC_OVERRIDE CAP_FOWNER"
render_unit r740-ai-autorouting.service "autorouting preview" auto_service 41155 "$SERVICE_USER" ""

PYTHONPATH="$INSTALL_DIR/components/core/src" "$VENV_DIR/bin/python" - "$CONFIG_DIR/core.env" <<'PY'
import os
from pathlib import Path
import shlex
import sys

for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    key, separator, value = line.partition("=")
    if not separator or not key.isidentifier():
        raise SystemExit(f"invalid core.env entry: {key}")
    parsed = shlex.split(value, posix=True)
    os.environ[key] = parsed[0] if parsed else ""
from r740_core.config import CoreSettings
settings = CoreSettings.from_env()
assert not settings.execution_enabled
PY
systemctl daemon-reload

echo "Core controller installed but all units remain disabled and stopped."
echo "Install and qualify model units first; then enable only the reviewed core units."
