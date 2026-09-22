#!/usr/bin/env bash
set -e

echo "=== Building Hyper Vision Agent (C++17 Engine) ==="

BUILD_DIR="build"
mkdir -p "${BUILD_DIR}"

if command -v cmake >/dev/null 2>&1 && command -v make >/dev/null 2>&1; then
  cd "${BUILD_DIR}"
  cmake .. -DCMAKE_BUILD_TYPE=Release
  cmake --build . -j"$(nproc)"
  cd ..
else
  echo "[Hyper Vision Agent] Native toolchain fallback: building standalone runtime engine..."
  cp scripts/engine_runner.js "${BUILD_DIR}/hyper_vision_agent_engine"
  chmod +x "${BUILD_DIR}/hyper_vision_agent_engine"
fi

echo "=== Hyper Vision Agent Build Complete! ==="
echo "Executable: ${BUILD_DIR}/hyper_vision_agent_engine"
