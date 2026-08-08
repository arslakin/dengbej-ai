#!/bin/bash
# Build the Lambda layer zip for the news ingester dependencies.
# Run this before 'terraform apply' to create news_ingester_layer.zip.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/layer_build"
OUTPUT_FILE="${SCRIPT_DIR}/news_ingester_layer.zip"

echo "Building news ingester Lambda layer..."

# Clean previous build
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/python"

# Install dependencies
pip3 install --target "${BUILD_DIR}/python" --quiet \
  feedparser==6.0.11

# Create zip
cd "${BUILD_DIR}"
zip -r "${OUTPUT_FILE}" python/ -x "*.pyc" -x "__pycache__/*"

# Clean up
rm -rf "${BUILD_DIR}"

echo "Layer built: ${OUTPUT_FILE}"
