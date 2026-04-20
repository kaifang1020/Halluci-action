#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Removing containers and volumes"
docker compose down -v --remove-orphans

echo "==> Rebuilding clean environment"
"$ROOT_DIR/scripts/init.sh"
