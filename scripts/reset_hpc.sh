#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONDA_ENV_NAME="${CONDA_ENV_NAME:-odoo-research}"
DB_NAME="${ODOO_DB_NAME:-${ODOO_DB:-odoo_research}}"
PG_PORT="${PG_PORT:-5432}"
DATA_ROOT="${DATA_ROOT:-/gpfsnyu/scratch/km6704/odoo-research}"
ODOO_DATA_DIR="${ODOO_DATA_DIR:-$DATA_ROOT/filestore}"
ODOO_LOGS_DIR="${ODOO_LOGS_DIR:-$DATA_ROOT/logs}"
MODULES="${ODOO_INIT_MODULES:-base,account,sale_management,crm,stock,purchase,mrp,project,hr_holidays,hr_attendance,point_of_sale}"

CONDA_BASE="$(conda info --base 2>/dev/null)" || { echo "ERROR: conda not found in PATH" >&2; exit 1; }
# shellcheck source=/dev/null
source "$CONDA_BASE/etc/profile.d/conda.sh"
crun() { conda run -n "$CONDA_ENV_NAME" --no-capture-output "$@"; }

CONDA_ENV_PATH="$(conda env list | awk -v n="$CONDA_ENV_NAME" '$1==n{print $NF}')"
ODOO_BIN="$CONDA_ENV_PATH/bin/odoo"
PSQL="$CONDA_ENV_PATH/bin/psql"
PID_FILE="$DATA_ROOT/odoo.pid"
LOCAL_CONF="$ROOT_DIR/.odoo-local.conf"

echo "==> Ensuring local HPC PostgreSQL/Odoo config exists"
bash "$ROOT_DIR/scripts/init_hpc.sh" --no-init

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "==> Stopping Odoo PID $(cat "$PID_FILE")"
  kill "$(cat "$PID_FILE")" || true
  for _ in $(seq 1 20); do
    kill -0 "$(cat "$PID_FILE")" 2>/dev/null || break
    sleep 1
  done
  rm -f "$PID_FILE"
fi

echo "==> Dropping database $DB_NAME"
crun "$PSQL" -h 127.0.0.1 -p "$PG_PORT" -U postgres -d postgres \
  -v ON_ERROR_STOP=1 \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME';" \
  -c "DROP DATABASE IF EXISTS $DB_NAME;"

rm -rf "$ODOO_DATA_DIR/filestore/$DB_NAME" "$ODOO_DATA_DIR/sessions"

echo "==> Reinitialising Odoo database $DB_NAME"
crun "$ODOO_BIN" \
  --config "$LOCAL_CONF" \
  --database "$DB_NAME" \
  --init "$MODULES" \
  --without-demo all \
  --stop-after-init

echo "==> Starting Odoo"
bash "$ROOT_DIR/scripts/init_hpc.sh" --no-init
