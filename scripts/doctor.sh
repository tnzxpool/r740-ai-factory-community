#!/bin/sh
# SPDX-License-Identifier: LGPL-3.0-or-later
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
MODE=${1:-auto}
FAILED=0
case "$MODE" in auto|compose|systemd) ;; *) echo "Usage: $0 [auto|compose|systemd]" >&2; exit 2;; esac
if [ "$MODE" = auto ]; then
  if [ -f "$PROJECT_DIR/config/runtime.env" ]; then MODE=compose; else MODE=systemd; fi
fi

pass() { printf 'PASS %s\n' "$*"; }
info() { printf 'INFO %s\n' "$*"; }
fail() { printf 'FAIL %s\n' "$*" >&2; FAILED=1; }
check_file() { if [ -r "$1" ]; then pass "file $1"; else fail "file $1"; fi; }

command -v python3 >/dev/null 2>&1 || { fail "python3 unavailable"; exit 1; }
python3 - <<'PY' || FAILED=1
import sys
if sys.version_info < (3, 10): raise SystemExit("FAIL Python 3.10 or newer required")
print("PASS Python", sys.version.split()[0])
PY

if [ "$MODE" = compose ]; then
  CONFIG_DIR="$PROJECT_DIR/config"; SECRET_DIR="$PROJECT_DIR/secrets"
  check_file "$CONFIG_DIR/runtime.env"; check_file "$SECRET_DIR/admin_token"
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    (cd "$PROJECT_DIR" && docker compose config --quiet) && pass "Compose configuration" || fail "Compose configuration"
    (cd "$PROJECT_DIR" && docker compose ps) || fail "Compose status"
    running=$(cd "$PROJECT_DIR" && docker compose ps --status running --services 2>/dev/null || true)
    printf '%s\n' "$running" | grep -Eq '^factory-(cpu|nvidia)$' && pass "factory container running" || fail "factory container is not running"
  else fail "Docker Compose v2 unavailable"; fi
  BASE_URL="http://127.0.0.1:${R740_HTTP_PORT:-8080}"
else
  CONFIG_DIR=${R740_CONFIG_DIR:-/etc/r740-ai-factory}
  INSTALL_DIR=${R740_INSTALL_DIR:-/opt/r740-ai-factory}
  STATE_DIR=${R740_STATE_DIR:-/var/lib/r740-ai-factory}
  check_file "$CONFIG_DIR/runtime.env"; check_file "$CONFIG_DIR/secrets/admin_token"
  check_file "$INSTALL_DIR/model-manifests/catalog.json"
  for unit in r740-ai-factory; do
    if systemctl list-unit-files "$unit.service" --no-legend 2>/dev/null | grep -q .; then
      state=$(systemctl is-active "$unit.service" 2>/dev/null || true)
      if [ "$state" = active ]; then pass "$unit active"; else fail "$unit state=$state"; fi
    else fail "$unit unit is not installed"; fi
  done
  for unit in r740-ai-portal r740-ai-gateway r740-ai-orchestrator r740-ai-model-manager r740-ai-graphics-manager; do
    if systemctl list-unit-files "$unit.service" --no-legend 2>/dev/null | grep -q .; then
      state=$(systemctl is-active "$unit.service" 2>/dev/null || true); info "$unit optional state=$state"
    fi
  done
  [ -d "$STATE_DIR" ] && pass "state directory $STATE_DIR" || info "state directory not created"
  PORT_FROM_ENV=$(python3 - "$CONFIG_DIR/runtime.env" <<'PY'
from pathlib import Path
import sys
value = "8080"
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if raw.startswith("R740_PORT="):
        value = raw.split("=", 1)[1].strip()
print(value)
PY
)
  BASE_URL="http://127.0.0.1:$PORT_FROM_ENV"
fi

if [ -r "$CONFIG_DIR/runtime.env" ]; then
  python3 - "$CONFIG_DIR/runtime.env" <<'PY' || FAILED=1
from pathlib import Path
import sys
keys = {}
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not raw or raw.startswith("#") or "=" not in raw: continue
    key, value = raw.split("=", 1); keys[key] = value
print("PASS runtime configuration parsed")
print("INFO inference backend", "configured" if keys.get("R740_INFERENCE_BASE_URL") else "not configured")
PY
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | sed 's/^/PASS NVIDIA /'
else info "NVIDIA unavailable; CPU/control-plane mode remains supported"; fi

if python3 - "$BASE_URL/healthz" <<'PY' 2>/dev/null
import sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=3) as response: raise SystemExit(0 if response.status == 200 else 1)
PY
then pass "control plane health $BASE_URL/healthz"; else fail "control plane not reachable at $BASE_URL"; fi

exit "$FAILED"
