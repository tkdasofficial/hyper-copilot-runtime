#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR}"
BUILD_DIR="${ROOT_DIR}/build"

echo "=== Hyper Editor: Building C++ Engine ==="
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

if command -v cmake >/dev/null 2>&1; then
    cmake -DCMAKE_BUILD_TYPE=Release "${ROOT_DIR}"
    make -j"$(nproc 2>/dev/null || echo 4)"
    echo "=== C++ Native Engine compiled successfully: ${BUILD_DIR}/hyper_editor ==="
else
    echo "CMake not found, falling back to direct g++ compilation..."
    g++ -std=c++17 -O3 \
        -I"${ROOT_DIR}/include" \
        -I"${ROOT_DIR}/extensions" \
        $(pkg-config --cflags --libs libavcodec libavformat libavfilter libswscale libswresample libavutil freetype2 harfbuzz 2>/dev/null || true) \
        -lpthread -lm \
        "${ROOT_DIR}/src/main.cpp" \
        "${ROOT_DIR}/src/core/editor.cpp" \
        "${ROOT_DIR}/src/core/ffmpeg_bridge.cpp" \
        "${ROOT_DIR}/src/core/timeline.cpp" \
        "${ROOT_DIR}/src/tools/"*.cpp \
        "${ROOT_DIR}/src/parsers/json_parser.cpp" \
        "${ROOT_DIR}/src/utils/"*.cpp \
        -o "${BUILD_DIR}/hyper_editor"
    echo "=== C++ Native Engine compiled: ${BUILD_DIR}/hyper_editor ==="
fi
