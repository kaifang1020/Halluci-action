#!/usr/bin/env bash
# =============================================================================
# init.sh — No-Docker bootstrap: conda env + local PostgreSQL + Odoo via pip
#
# Everything runs in user space; 
#
# First run  (~10–20 min):  creates conda env, installs PostgreSQL + Odoo,
#                           inits the DB cluster, seeds the Odoo database.
# Later runs (~10 sec):     just starts the already-installed services.
#
# Usage:
#   ./scripts/init.sh            # full bootstrap / start
#   ./scripts/init.sh --no-init  # skip DB init, only start services
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# ---------------------------------------------------------------------------
# Config  (override via environment variables)
# ---------------------------------------------------------------------------
CONDA_ENV_NAME="${CONDA_ENV_NAME:-odoo-research}"
PYTHON_VERSION="${PYTHON_VERSION:-3.10}"

DB_NAME="${ODOO_DB_NAME:-odoo_research}"
DB_USER="${ODOO_DB_USER:-odoo}"
DB_PASS="${ODOO_DB_PASS:-odoo_pw}"
PG_PORT="${PG_PORT:-5432}"

# All persistent data goes to /data2 to protect home-dir quota
DATA_ROOT="/scratch/km6704/odoo-research"
PG_DATA_DIR="${PG_DATA_DIR:-$DATA_ROOT/pgdata}"
ODOO_DATA_DIR="${ODOO_DATA_DIR:-$DATA_ROOT/filestore}"
ODOO_LOGS_DIR="${ODOO_LOGS_DIR:-$DATA_ROOT/logs}"
ODOO_SRC_DIR="${ODOO_SRC_DIR:-$DATA_ROOT/odoo-src}"

MODULES="${ODOO_INIT_MODULES:-base,sale_management,crm,stock,project,hr_attendance,point_of_sale}"
HTTP_PORT="${ODOO_HTTP_PORT:-8069}"

SKIP_INIT=false
[[ "${1:-}" == "--no-init" ]] && SKIP_INIT=true

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

# Activate conda inside a non-interactive shell
CONDA_BASE="$(conda info --base 2>/dev/null)" \
  || die "conda not found in PATH"
# shellcheck source=/dev/null
source "$CONDA_BASE/etc/profile.d/conda.sh"

# Run a command inside the conda env
crun() { conda run -n "$CONDA_ENV_NAME" --no-capture-output "$@"; }

# ---------------------------------------------------------------------------
# Step 1: Create / update conda environment
# ---------------------------------------------------------------------------
if ! conda env list | awk '{print $1}' | grep -qx "$CONDA_ENV_NAME"; then
    log "Creating conda env '$CONDA_ENV_NAME' (Python $PYTHON_VERSION)"
    conda create -y -n "$CONDA_ENV_NAME" \
        python="$PYTHON_VERSION" \
        -c conda-forge
else
    log "Conda env '$CONDA_ENV_NAME' already exists — skipping create"
fi

# Install PostgreSQL 15 server inside the env (conda-forge build is self-contained)
if ! crun pg_ctl --version &>/dev/null 2>&1; then
    log "Installing PostgreSQL via conda-forge"
    conda install -y -n "$CONDA_ENV_NAME" -c conda-forge "postgresql=15.*"
else
    log "PostgreSQL already installed in env"
fi

# ---------------------------------------------------------------------------
# Step 2: Install Odoo 17 from GitHub (into the conda env via pip)
# ---------------------------------------------------------------------------
if ! crun python -c "import odoo" &>/dev/null 2>&1; then
    log "Cloning Odoo 17 source → $ODOO_SRC_DIR"
    mkdir -p "$ODOO_SRC_DIR"
    if [ ! -d "$ODOO_SRC_DIR/.git" ]; then
        git clone --depth 1 --branch 17.0 \
            https://github.com/odoo/odoo.git "$ODOO_SRC_DIR"
    fi
    log "Installing compiled dependencies from conda-forge"
    # gevent + greenlet must be installed together so conda can resolve the
    # compatible pair (newer greenlet>=2.0 removed the 'parent' C struct field
    # that older gevent relied on).
    # python-ldap bundles OpenLDAP headers, avoiding the missing lber.h error.
    conda install -y -n "$CONDA_ENV_NAME" -c conda-forge \
        gevent \
        greenlet \
        "lxml>=4.8.0" \
        "pillow>=9.0.0" \
        psycopg2 \
        python-ldap

    # Odoo's requirements.txt pins exact versions like gevent==21.8.0 which
    # conflict with the newer conda-forge versions we just installed.
    # Solution: comment out those lines before passing the file to pip.
    FILTERED_REQ="/tmp/odoo17_requirements_filtered.txt"
    sed -E \
        's/^(gevent|greenlet|lxml|Pillow|psycopg2|python-ldap)[>=<!].*/# & (managed by conda)/' \
        "$ODOO_SRC_DIR/requirements.txt" > "$FILTERED_REQ"
    log "Filtered requirements (conda-managed lines commented out)"

    # setuptools>=70 removed pkg_resources from the default namespace;
    # Odoo 17 imports it directly, so we need a compatible setuptools version.
    crun pip install --cache-dir /scratch/km6704/pip-cache "setuptools<70"

    log "Installing remaining Odoo Python requirements via pip"
    crun pip install --cache-dir /scratch/km6704/pip-cache \
        -r "$FILTERED_REQ"

    # lxml>=5 split lxml.html.clean into a separate package; install it now.
    crun pip install --cache-dir /scratch/km6704/pip-cache lxml_html_clean

    log "Installing Odoo package (editable, --no-deps skips re-checking versions)"
    crun pip install --cache-dir /scratch/km6704/pip-cache \
        --no-deps \
        -e "$ODOO_SRC_DIR"
else
    log "Odoo already installed in env"
fi

# Locate odoo-bin inside the env
CONDA_ENV_PATH="$(conda env list | awk -v n="$CONDA_ENV_NAME" '$1==n{print $NF}')"
ODOO_BIN="$CONDA_ENV_PATH/bin/odoo"
PG_CTL="$CONDA_ENV_PATH/bin/pg_ctl"
PG_ISREADY="$CONDA_ENV_PATH/bin/pg_isready"
PSQL="$CONDA_ENV_PATH/bin/psql"
INITDB="$CONDA_ENV_PATH/bin/initdb"
CREATEUSER="$CONDA_ENV_PATH/bin/createuser"

# ---------------------------------------------------------------------------
# Step 3: Init PostgreSQL cluster (first time only)
# ---------------------------------------------------------------------------
mkdir -p "$PG_DATA_DIR" "$ODOO_DATA_DIR" "$ODOO_LOGS_DIR"

if [ ! -f "$PG_DATA_DIR/PG_VERSION" ]; then
    log "Initialising PostgreSQL cluster at $PG_DATA_DIR"
    crun "$INITDB" \
        -D "$PG_DATA_DIR" \
        -U postgres \
        --auth=trust \
        -E UTF8 \
        --locale=en_US.UTF-8
    # Restrict to localhost only
    printf "\n# allow local connections\nhost all all 127.0.0.1/32 md5\nhost all all ::1/128 md5\n" \
        >> "$PG_DATA_DIR/pg_hba.conf"
fi

# ---------------------------------------------------------------------------
# Step 4: Start PostgreSQL
# ---------------------------------------------------------------------------
PG_LOG="$ODOO_LOGS_DIR/postgres.log"
if ! crun "$PG_ISREADY" -h 127.0.0.1 -p "$PG_PORT" &>/dev/null 2>&1; then
    log "Starting PostgreSQL (port $PG_PORT)"
    crun "$PG_CTL" -D "$PG_DATA_DIR" \
        -l "$PG_LOG" \
        -o "-p $PG_PORT" \
        start
    log "Waiting for PostgreSQL to accept connections"
    for i in $(seq 1 30); do
        crun "$PG_ISREADY" -h 127.0.0.1 -p "$PG_PORT" &>/dev/null && break
        sleep 2
    done
    crun "$PG_ISREADY" -h 127.0.0.1 -p "$PG_PORT" \
        || die "PostgreSQL did not start. Check $PG_LOG"
else
    log "PostgreSQL already running on port $PG_PORT"
fi

# ---------------------------------------------------------------------------
# Step 5: Create DB role for Odoo (idempotent)
# ---------------------------------------------------------------------------
PSQL_SU="crun $PSQL -h 127.0.0.1 -p $PG_PORT -U postgres -d postgres"

if ! $PSQL_SU -tc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" \
        2>/dev/null | grep -q 1; then
    log "Creating PostgreSQL role '$DB_USER'"
    $PSQL_SU -c \
        "CREATE ROLE $DB_USER WITH LOGIN CREATEDB PASSWORD '$DB_PASS';"
fi

# ---------------------------------------------------------------------------
# Step 6: Write a local odoo.conf
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Step 7: Initialise the Odoo database (first time, or unless --no-init)
# ---------------------------------------------------------------------------
DB_EXISTS=$(crun "$PSQL" -h 127.0.0.1 -p "$PG_PORT" -U postgres -d postgres \
    -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null \
    | tr -d ' ' || true)

if [[ "$SKIP_INIT" == false && "$DB_EXISTS" != "1" ]]; then
    log "Initialising Odoo database '${DB_NAME}' (this may take several minutes)"
    crun "$ODOO_BIN" \
        --config "$LOCAL_CONF" \
        --database "$DB_NAME" \
        --init "$MODULES" \
        --without-demo all \
        --stop-after-init
    log "Database initialised"
elif [[ "$DB_EXISTS" == "1" ]]; then
    log "Database '${DB_NAME}' already exists — skipping --init"
fi

# ---------------------------------------------------------------------------
# Step 8: Start Odoo web service in the background
# ---------------------------------------------------------------------------
PID_FILE="$DATA_ROOT/odoo.pid"
ODOO_LOG="$ODOO_LOGS_DIR/odoo.log"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    log "Odoo is already running (PID $(cat "$PID_FILE"))"
else
    log "Starting Odoo web service"
    crun "$ODOO_BIN" \
        --config "$LOCAL_CONF" \
        --logfile "$ODOO_LOG" \
        &
    echo $! > "$PID_FILE"
fi

echo
echo "Odoo is starting."
echo "  Web UI:     http://localhost:${HTTP_PORT}"
echo "  PostgreSQL: localhost:${PG_PORT}  db=${DB_NAME}  user=${DB_USER}"
echo "  Admin:      admin / admin"
echo "  Logs:       $ODOO_LOGS_DIR/"
echo
echo "To stop Odoo:      kill \$(cat $PID_FILE)"
echo "To stop Postgres:  conda run -n $CONDA_ENV_NAME $PG_CTL -D $PG_DATA_DIR stop"