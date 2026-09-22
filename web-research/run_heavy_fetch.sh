#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"
ENGINE_BIN="${BUILD_DIR}/hyper_vision_agent_engine"

# Ensure binary is built
if [ ! -f "$ENGINE_BIN" ]; then
  echo "[Hyper Vision] Engine binary not found, building via CMake..."
  mkdir -p "$BUILD_DIR"
  cd "$BUILD_DIR"
  cmake -DCMAKE_BUILD_TYPE=Release ..
  cmake --build . -j"$(nproc)"
  cd "$SCRIPT_DIR"
fi

OUTPUT_DIR="${SCRIPT_DIR}/research_output"
mkdir -p "$OUTPUT_DIR"

MODE="$1"
TARGET="$2"

if [ -z "$MODE" ]; then
  echo "Usage: ./run_heavy_fetch.sh [--fetch <url> | --research <query>]"
  exit 1
fi

echo "[Hyper Vision] Running Native C++ Heavy Engine ($MODE: $TARGET)..."
"$ENGINE_BIN" "$MODE" "$TARGET" "$OUTPUT_DIR"
