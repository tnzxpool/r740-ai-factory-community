#!/bin/sh
# SPDX-License-Identifier: LGPL-3.0-or-later
set -eu

CONFIG_DIR=${R740_CONFIG_DIR:-/etc/r740-ai-factory}
INSTALL_DIR=${R740_INSTALL_DIR:-/opt/r740-ai-factory}
STATE_DIR=${R740_STATE_DIR:-/var/lib/r740-ai-factory}
FAILED=0

check_file() {
  if [ -r "$1" ]; then
    printf 'PASS file %s\n' "$1"
  else
    printf 'FAIL file %s\n' "$1" >&2
    FAILED=1
  fi
}

command -v python3 >/dev/null 2>&1 || {
  printf 'FAIL python3 unavailable\n' >&2
  exit 1
}

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("FAIL Python 3.10 or newer required")
print("PASS Python", sys.version.split()[0])
PY

check_file "$CONFIG_DIR/runtime.env"
check_file "$CONFIG_DIR/secrets/admin_token"
check_file "$INSTALL_DIR/model-manifests/catalog.json"

if [ -r "$CONFIG_DIR/secrets/admin_token" ]; then
  python3 - "$CONFIG_DIR/secrets/admin_token" <<'PY'
from pathlib import Path
import sys
value = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
if len(value) < 32:
    raise SystemExit("FAIL admin token is too short")
print("PASS admin token present (value hidden)")
PY
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader |
    sed 's/^/PASS NVIDIA /'
else
  printf 'INFO NVIDIA unavailable; CPU/control-plane mode remains supported\n'
fi

if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet r740-ai-factory 2>/dev/null; then
  printf 'PASS service active\n'
else
  printf 'INFO service inactive or systemd unavailable\n'
fi

if [ -d "$STATE_DIR" ]; then
  printf 'PASS state directory %s\n' "$STATE_DIR"
else
  printf 'INFO state directory not created yet\n'
fi

exit "$FAILED"

