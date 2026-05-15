#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${1:?Usage: $0 <app-name>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

case "$(uname -s)" in
  Darwin)
    DEST="dist/${APP_NAME}.app/Contents/Resources"
    ;;
  *)
    DEST="dist/main.dist/resources"
    ;;
esac

echo "Staging assets into ${DEST}..."
mkdir -p "${DEST}"
cp -r "${PROJECT_DIR}/resources/"* "${DEST}/"
echo "Assets staged successfully"
