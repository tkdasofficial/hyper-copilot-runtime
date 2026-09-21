#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ ! -f "${ROOT_DIR}/build/hyper_editor" ]; then
    "${SCRIPT_DIR}/build.sh"
fi

exec "${ROOT_DIR}/build/hyper_editor" --serve 3000
