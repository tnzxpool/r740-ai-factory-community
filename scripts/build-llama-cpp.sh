#!/bin/sh
# SPDX-License-Identifier: LGPL-3.0-or-later
set -eu

REVISION=${R740_LLAMA_CPP_REVISION:-8d274dd7c6233ed73c7509cc2a8be9960f7df7d5}
SOURCE_DIR=${R740_LLAMA_CPP_SOURCE:-$PWD/build/llama.cpp-src}
BUILD_DIR=${R740_LLAMA_CPP_BUILD:-$PWD/build/llama.cpp-build}
MODE=${1:-cuda-p40}

case "$MODE" in cuda-p40|cuda|cpu) ;; *) echo "Usage: $0 [cuda-p40|cuda|cpu]" >&2; exit 2;; esac
for command in git cmake; do command -v "$command" >/dev/null 2>&1 || { echo "FAIL $command is required" >&2; exit 1; }; done
if [ "$MODE" != cpu ] && ! command -v nvcc >/dev/null 2>&1; then
  echo "FAIL nvcc/CUDA toolkit is required for $MODE" >&2; exit 1
fi

if [ ! -d "$SOURCE_DIR/.git" ]; then
  [ ! -e "$SOURCE_DIR" ] || { echo "FAIL source path exists but is not a Git checkout: $SOURCE_DIR" >&2; exit 1; }
  mkdir -p "$SOURCE_DIR"
  git -C "$SOURCE_DIR" init -q
  git -C "$SOURCE_DIR" remote add origin https://github.com/ggml-org/llama.cpp.git
fi
git -C "$SOURCE_DIR" fetch --depth 1 origin "$REVISION"
git -C "$SOURCE_DIR" checkout --detach FETCH_HEAD
test "$(git -C "$SOURCE_DIR" rev-parse HEAD)" = "$REVISION" || { echo "FAIL revision mismatch" >&2; exit 1; }

[ ! -e "$BUILD_DIR" ] || { echo "FAIL build directory already exists; choose a new R740_LLAMA_CPP_BUILD path" >&2; exit 1; }
case "$MODE" in
  cuda-p40) cmake -S "$SOURCE_DIR" -B "$BUILD_DIR" -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=61 -DLLAMA_CURL=OFF -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release ;;
  cuda) cmake -S "$SOURCE_DIR" -B "$BUILD_DIR" -DGGML_CUDA=ON -DLLAMA_CURL=OFF -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release ;;
  cpu) cmake -S "$SOURCE_DIR" -B "$BUILD_DIR" -DGGML_CUDA=OFF -DLLAMA_CURL=OFF -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release ;;
esac
cmake --build "$BUILD_DIR" --config Release --target llama-server -j "${R740_BUILD_JOBS:-2}"
RUNTIME="$BUILD_DIR/bin/llama-server"
[ -x "$RUNTIME" ] || { echo "FAIL llama-server was not produced" >&2; exit 1; }
printf 'PASS llama.cpp revision=%s runtime=%s\n' "$REVISION" "$RUNTIME"
printf 'Next: place a licensed GGUF under /var/lib/r740-ai-factory/models and run scripts/register-local-model.py.\n'
