#!/bin/sh
# SPDX-License-Identifier: LGPL-3.0-or-later
set -eu

VERSION=${1:-0.2.0}
case "$VERSION" in *[!0-9A-Za-z._-]*|'') echo "invalid version" >&2; exit 2;; esac
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 1; }
command -v gzip >/dev/null 2>&1 || { echo "gzip is required" >&2; exit 1; }
[ -z "$(git status --porcelain --untracked-files=normal)" ] || {
  echo "release tree must be clean" >&2; exit 1;
}
mkdir -p dist
archive="dist/r740-ai-factory-community-$VERSION.tar.gz"
checksum="$archive.sha256"
[ ! -e "$archive" ] && [ ! -e "$checksum" ] || {
  echo "refusing to overwrite an existing release artifact" >&2; exit 1;
}
temporary=$(mktemp "${TMPDIR:-/tmp}/r740-release.XXXXXX.tar")
trap 'rm -f "$temporary"' EXIT HUP INT TERM
git archive --format=tar --prefix="r740-ai-factory-community-$VERSION/" HEAD > "$temporary"
gzip -n -9 < "$temporary" > "$archive"
sha256sum "$archive" > "$checksum"
printf 'PASS %s\n' "$archive"
