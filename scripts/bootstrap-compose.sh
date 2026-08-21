#!/bin/sh
# SPDX-License-Identifier: LGPL-3.0-or-later
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PROFILE=${1:-cpu}
ACTION=${2:-start}

case "$PROFILE" in cpu|nvidia|portal) ;; *) echo "Usage: $0 [cpu|nvidia|portal] [start|prepare]" >&2; exit 2;; esac
case "$ACTION" in start|prepare) ;; *) echo "Usage: $0 [cpu|nvidia|portal] [start|prepare]" >&2; exit 2;; esac

cd "$PROJECT_DIR"
"$SCRIPT_DIR/preflight.sh" "compose-$PROFILE"
"$SCRIPT_DIR/first-run.sh"
docker compose --profile "$PROFILE" config --quiet

if [ "$ACTION" = prepare ]; then
  echo "PASS configuration prepared; start with: docker compose --profile $PROFILE up -d --build"
  exit 0
fi

docker compose --profile "$PROFILE" up -d --build
case "$PROFILE" in
  portal) service=portal; url="http://127.0.0.1:${R740_PORTAL_PORT:-8081}/health" ;;
  cpu) service=factory-cpu; url="http://127.0.0.1:${R740_HTTP_PORT:-8080}/healthz" ;;
  nvidia) service=factory-nvidia; url="http://127.0.0.1:${R740_HTTP_PORT:-8080}/healthz" ;;
esac

i=0
while [ "$i" -lt 30 ]; do
  if python3 - "$url" <<'PY' 2>/dev/null
import sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=2) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
  then
    echo "PASS $service is ready at $url"
    if [ "$PROFILE" = portal ]; then
      echo "Setup token file: $PROJECT_DIR/secrets/setup_token (value intentionally not printed)"
      echo "For a remote host, keep the loopback bind and use an SSH tunnel; see docs/INSTALL.md."
    else
      echo "Administrator token file: $PROJECT_DIR/secrets/admin_token (value intentionally not printed)"
      echo "Inference works after R740_INFERENCE_BASE_URL points to a trusted OpenAI-compatible backend."
    fi
    exit 0
  fi
  i=$((i + 1)); sleep 2
done

docker compose --profile "$PROFILE" ps >&2 || true
docker compose --profile "$PROFILE" logs --tail=80 "$service" >&2 || true
echo "FAIL service did not become healthy within 60 seconds" >&2
exit 1
