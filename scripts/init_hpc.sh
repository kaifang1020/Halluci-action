#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONDA_ENV_NAME="${CONDA_ENV_NAME:-odoo-research}"
DB_NAME="${ODOO_DB_NAME:-${ODOO_DB:-odoo_research}}"
DB_USER="${ODOO_DB_USER:-odoo}"
DB_PASS="${ODOO_DB_PASS:-odoo_pw}"
PG_PORT="${PG_PORT:-5432}"
HTTP_PORT="${ODOO_HTTP_PORT:-8069}"

DATA_ROOT="${DATA_ROOT:-/gpfsnyu/scratch/km6704/odoo-research}"
PG_DATA_DIR="${PG_DATA_DIR:-$DATA_ROOT/pgdata}"
ODOO_DATA_DIR="${ODOO_DATA_DIR:-$DATA_ROOT/filestore}"
ODOO_LOGS_DIR="${ODOO_LOGS_DIR:-$DATA_ROOT/logs}"
ODOO_SRC_DIR="${ODOO_SRC_DIR:-$DATA_ROOT/odoo-src}"
MODULES="${ODOO_INIT_MODULES:-base,account,sale_management,crm,stock,purchase,mrp,project,hr_holidays,hr_attendance,point_of_sale}"

SKIP_INIT=false
[[ "${1:-}" == "--no-init" ]] && SKIP_INIT=true

log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

CONDA_BASE="$(conda info --base 2>/dev/null)" || die "conda not found in PATH"
# shellcheck source=/dev/null
source "$CONDA_BASE/etc/profile.d/conda.sh"
crun() { conda run -n "$CONDA_ENV_NAME" --no-capture-output "$@"; }

CONDA_ENV_PATH="$(conda env list | awk -v n="$CONDA_ENV_NAME" '$1==n{print $NF}')"
[[ -n "$CONDA_ENV_PATH" ]] || die "conda env '$CONDA_ENV_NAME' not found; run the original HPC bootstrap first"

ODOO_BIN="$CONDA_ENV_PATH/bin/odoo"
PG_CTL="$CONDA_ENV_PATH/bin/pg_ctl"
PG_ISREADY="$CONDA_ENV_PATH/bin/pg_isready"
PSQL="$CONDA_ENV_PATH/bin/psql"
INITDB="$CONDA_ENV_PATH/bin/initdb"

[[ -x "$ODOO_BIN" ]] || die "Odoo is not installed at $ODOO_BIN; run the original HPC bootstrap first"
[[ -x "$PG_CTL" ]] || die "PostgreSQL is not installed in conda env '$CONDA_ENV_NAME'"

mkdir -p "$PG_DATA_DIR" "$ODOO_DATA_DIR" "$ODOO_LOGS_DIR"

if [[ ! -f "$PG_DATA_DIR/PG_VERSION" ]]; then
  log "Initialising PostgreSQL cluster at $PG_DATA_DIR"
  crun "$INITDB" -D "$PG_DATA_DIR" -U postgres --auth=trust -E UTF8 --locale=en_US.UTF-8
  printf "\n# allow local connections\nhost all all 127.0.0.1/32 md5\nhost all all ::1/128 md5\n" >> "$PG_DATA_DIR/pg_hba.conf"
fi

PG_LOG="$ODOO_LOGS_DIR/postgres.log"
if ! crun "$PG_ISREADY" -h 127.0.0.1 -p "$PG_PORT" >/dev/null 2>&1; then
  log "Starting PostgreSQL on port $PG_PORT"
  crun "$PG_CTL" -D "$PG_DATA_DIR" -l "$PG_LOG" -o "-p $PG_PORT" start
  for _ in $(seq 1 30); do
    crun "$PG_ISREADY" -h 127.0.0.1 -p "$PG_PORT" >/dev/null 2>&1 && break
    sleep 2
  done
  crun "$PG_ISREADY" -h 127.0.0.1 -p "$PG_PORT" >/dev/null 2>&1 || die "PostgreSQL did not start; check $PG_LOG"
else
  log "PostgreSQL already running on port $PG_PORT"
fi

if ! crun "$PSQL" -h 127.0.0.1 -p "$PG_PORT" -U postgres -d postgres \
  -tc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" 2>/dev/null | grep -q 1; then
  log "Creating PostgreSQL role '$DB_USER'"
  crun "$PSQL" -h 127.0.0.1 -p "$PG_PORT" -U postgres -d postgres \
    -c "CREATE ROLE $DB_USER WITH LOGIN CREATEDB PASSWORD '$DB_PASS';"
fi

LOCAL_CONF="$ROOT_DIR/.odoo-local.conf"
cat > "$LOCAL_CONF" <<EOF
[options]
addons_path = $ROOT_DIR/custom_addons,$ODOO_SRC_DIR/addons,$ODOO_SRC_DIR/odoo/addons
data_dir = $ODOO_DATA_DIR
admin_passwd = admin
db_host = 127.0.0.1
db_port = $PG_PORT
db_user = $DB_USER
db_password = $DB_PASS
dbfilter = ^${DB_NAME}$
list_db = True
without_demo = all
log_level = info
xmlrpc_interface = 0.0.0.0
http_port = $HTTP_PORT
workers = 0
EOF

DB_EXISTS="$(crun "$PSQL" -h 127.0.0.1 -p "$PG_PORT" -U postgres -d postgres \
  -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null | tr -d ' ' || true)"

if [[ "$SKIP_INIT" == false && "$DB_EXISTS" != "1" ]]; then
  log "Initialising Odoo database '$DB_NAME'"
  crun "$ODOO_BIN" \
    --config "$LOCAL_CONF" \
    --database "$DB_NAME" \
    --init "$MODULES" \
    --without-demo all \
    --stop-after-init
elif [[ "$DB_EXISTS" == "1" ]]; then
  log "Database '$DB_NAME' already exists"
fi

PID_FILE="$DATA_ROOT/odoo.pid"
ODOO_LOG="$ODOO_LOGS_DIR/odoo.log"
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  log "Odoo already running, PID $(cat "$PID_FILE")"
else
  log "Starting Odoo web service on port $HTTP_PORT"
  setsid nohup "$ODOO_BIN" --config "$LOCAL_CONF" --logfile "$ODOO_LOG" </dev/null >/dev/null 2>&1 &
  echo $! > "$PID_FILE"
fi

echo
echo "Odoo:      http://localhost:${HTTP_PORT}"
echo "Postgres:  localhost:${PG_PORT} db=${DB_NAME} user=${DB_USER}"
echo "Logs:      $ODOO_LOGS_DIR/"
