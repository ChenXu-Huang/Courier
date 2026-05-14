#!/usr/bin/env bash
set -euo pipefail

REF_NAME="${1:-}"

if [[ "${REF_NAME}" =~ ^v[0-9] ]]; then
  echo "${REF_NAME#v}"
else
  echo "0.0.1"
fi
