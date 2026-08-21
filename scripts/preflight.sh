#!/bin/sh
# SPDX-License-Identifier: LGPL-3.0-or-later
set -eu

MODE=${1:-compose-cpu}
FAILED=0

pass() { printf 'PASS %s\n' "$*"; }
warn() { printf 'WARN %s\n' "$*" >&2; }
fail() { printf 'FAIL %s\n' "$*" >&2; FAILED=1; }

case "$MODE" in
  compose-cpu|compose-nvidia|compose-portal|systemd-control|systemd-portal|systemd-core|systemd-model) ;;
  *) echo "Usage: $0 [compose-cpu|compose-nvidia|compose-portal|systemd-control|systemd-portal|systemd-core|systemd-model]" >&2; exit 2 ;;
esac

case "$(uname -s 2>/dev/null || echo unknown)" in
  Linux) pass "Linux host" ;;
  *) fail "Linux is required for installation (Windows is supported only for Local-MCP)" ;;
esac

if command -v python3 >/dev/null 2>&1; then
  if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'; then
    pass "Python $(python3 -c 'import platform; print(platform.python_version())')"
  else
    fail "Python 3.10 or newer is required (3.11+ for portal/core)"
  fi
else
  fail "python3 is not installed"
fi

case "$MODE" in
  compose-portal|systemd-portal|systemd-core)
    python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' || fail "Python 3.11 or newer is required for portal/core"
    ;;
esac

available_kib=$(df -Pk . 2>/dev/null | awk 'NR==2 {print $4}')
if [ -n "${available_kib:-}" ] && [ "$available_kib" -ge 5242880 ]; then
  pass "at least 5 GiB free for application files"
else
  warn "less than 5 GiB free; model weights require substantially more space"
fi

case "$MODE" in
  compose-*)
    [ "$(id -u)" -ne 0 ] || fail "run Compose as an unprivileged user with Docker access, not through sudo"
    command -v docker >/dev/null 2>&1 || fail "Docker Engine is not installed"
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
      pass "Docker Compose v2"
    else
      fail "Docker Compose v2 is unavailable"
    fi
    ;;
  systemd-*)
    command -v systemctl >/dev/null 2>&1 || fail "systemd is required"
    [ -d /run/systemd/system ] || fail "systemd is not running as PID 1"
    command -v useradd >/dev/null 2>&1 || fail "useradd is required"
    command -v install >/dev/null 2>&1 || fail "GNU install is required"
    if [ "$(id -u)" -eq 0 ]; then pass "running as root"; else fail "systemd installation must run as root"; fi
    ;;
esac

case "$MODE" in
  systemd-core|systemd-model)
    command -v usermod >/dev/null 2>&1 || fail "usermod is required"
    command -v getent >/dev/null 2>&1 || fail "getent is required"
    command -v runuser >/dev/null 2>&1 || fail "runuser is required"
    ;;
esac

case "$MODE" in
  *nvidia|systemd-core|systemd-model)
    if command -v nvidia-smi >/dev/null 2>&1; then
      nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader 2>/dev/null | sed 's/^/PASS NVIDIA /'
    else
      fail "nvidia-smi is required for the NVIDIA/P40 path"
    fi
    if command -v nvcc >/dev/null 2>&1; then pass "CUDA compiler available"; else warn "nvcc absent; needed only when building llama.cpp locally"; fi
    if [ "$MODE" = compose-nvidia ]; then
      if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q 'nvidia'; then
        pass "NVIDIA Container Toolkit runtime"
      else
        fail "NVIDIA Container Toolkit is not configured for Docker"
      fi
    fi
    ;;
esac

if [ "$FAILED" -ne 0 ]; then
  echo "Preflight failed; no installation action was performed." >&2
  exit 1
fi
echo "PASS preflight $MODE"
