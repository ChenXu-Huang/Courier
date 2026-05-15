#!/usr/bin/env bash
set -euo pipefail

REF_NAME="${1:?Usage: $0 <ref-name> <os-name>}"
OS_NAME="${2:?Usage: $0 <ref-name> <os-name>}"

if [[ "${REF_NAME}" =~ ^v[0-9] ]]; then
  CLEAN_VERSION="${REF_NAME#v}"
else
  CLEAN_VERSION="0.0.1"
fi

echo "CLEAN_VERSION=${CLEAN_VERSION}"
echo "SHORT_OS=${OS_NAME%-latest}"
