#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/processor_layer_build"
OUTPUT_FILE="${SCRIPT_DIR}/processor_layer.zip"

echo "Building processor Lambda layer..."

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/python"

pip3 install --target "${BUILD_DIR}/python" --quiet \
    requests==2.31.0 \
    beautifulsoup4==4.12.3

cd "${BUILD_DIR}"
zip -r "${OUTPUT_FILE}" python/ -x "*.pyc" -x "__pycache__/*"

rm -rf "${BUILD_DIR}"

echo "Layer built: ${OUTPUT_FILE}"
