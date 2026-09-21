#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/build"

echo "=== Hyper Editor Agent: Building Project ==="
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

cmake -DCMAKE_BUILD_TYPE=Release "${ROOT_DIR}"
make -j"$(nproc 2>/dev/null || echo 4)"

echo "=== Build Complete! Executable located at: ${BUILD_DIR}/hyper_editor ==="
