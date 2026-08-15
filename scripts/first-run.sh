#!/bin/sh
# SPDX-License-Identifier: LGPL-3.0-or-later
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
CONFIG_DIR=${R740_CONFIG_DIR:-"$PROJECT_DIR/config"}
SECRET_DIR=${R740_SECRET_DIR:-"$PROJECT_DIR/secrets"}
DATA_DIR=${R740_DATA_DIR:-"$PROJECT_DIR/data"}
MODEL_DIR=${R740_MODEL_DIR:-"$PROJECT_DIR/models"}

umask 077
mkdir -p "$CONFIG_DIR" "$SECRET_DIR" "$DATA_DIR" "$MODEL_DIR"

TOKEN_FILE="$SECRET_DIR/admin_token"
if [ ! -s "$TOKEN_FILE" ]; then
  python3 - "$TOKEN_FILE" <<'PY'
import secrets
import sys
from pathlib import Path

target = Path(sys.argv[1])
target.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
PY
fi
chmod 600 "$TOKEN_FILE"

SETUP_TOKEN_FILE="$SECRET_DIR/setup_token"
if [ ! -s "$SETUP_TOKEN_FILE" ]; then
  python3 - "$SETUP_TOKEN_FILE" <<'PY'
import secrets
import sys
from pathlib import Path

target = Path(sys.argv[1])
target.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
PY
fi
chmod 600 "$SETUP_TOKEN_FILE"

RUNTIME_FILE="$CONFIG_DIR/runtime.env"
if [ ! -e "$RUNTIME_FILE" ]; then
  cp "$PROJECT_DIR/config/runtime.env.example" "$RUNTIME_FILE"
fi
chmod 600 "$RUNTIME_FILE"

PORTAL_RUNTIME_FILE="$CONFIG_DIR/portal.env"
if [ ! -e "$PORTAL_RUNTIME_FILE" ]; then
  cp "$PROJECT_DIR/components/portal/runtime.env.example" "$PORTAL_RUNTIME_FILE"
fi
chmod 600 "$PORTAL_RUNTIME_FILE"

printf '%s\n' "First-run configuration created."
printf '%s\n' "Admin token stored at: $TOKEN_FILE"
printf '%s\n' "The token value was not printed."
