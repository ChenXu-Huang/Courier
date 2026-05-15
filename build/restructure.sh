#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

case "$(uname -s)" in
  Darwin)
    DEST="dist/main.app/Contents/Resources"
    ;;
  *)
    DEST="dist/main.dist/resources"
    ;;
esac

echo "Staging assets into ${DEST}..."
mkdir -p "${DEST}"
cp -r "${PROJECT_DIR}/resources/"* "${DEST}/"
echo "Assets staged successfully"
