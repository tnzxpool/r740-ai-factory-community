#!/bin/sh
# SPDX-License-Identifier: LGPL-3.0-or-later
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

python3 tests/package_audit.py
python3 tests/source_import_test.py
python3 tests/sbom_test.py
python3 tests/portal_installer_test.py
python3 tests/smoke_test.py
python3 -m compileall -q src scripts tests

for script in scripts/*.sh; do
    sh -n "$script"
done

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose --profile cpu config --quiet
else
    echo "WARN Docker Compose unavailable; container clean-install gate remains pending" >&2
fi

if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    test -z "$(git status --porcelain)" || {
        echo "FAIL release tree is dirty" >&2
        exit 1
    }
fi

echo "PASS local release gate"
