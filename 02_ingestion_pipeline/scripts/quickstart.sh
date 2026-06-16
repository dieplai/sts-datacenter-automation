#!/usr/bin/env bash
# Backward-compatible entrypoint for the first-time local setup.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

bash scripts/first-run.sh
