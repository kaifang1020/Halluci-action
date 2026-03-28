#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DB_NAME="${ODOO_DB_NAME:-odoo_research}"
MODULES="${ODOO_INIT_MODULES:-base,crm,stock,project,hr_attendance,point_of_sale}"

echo "==> Starting PostgreSQL"
docker compose up -d db

echo "==> Waiting for PostgreSQL to become ready"
until docker compose exec -T db pg_isready -U odoo -d postgres >/dev/null 2>&1; do
  sleep 2
done

echo "==> Initializing database: ${DB_NAME}"
docker compose run --rm odoo odoo \
  --config /etc/odoo/odoo.conf \
  --database "${DB_NAME}" \
  --init "${MODULES}" \
  --without-demo all \
  --stop-after-init

echo "==> Starting Odoo web service"
docker compose up -d odoo

echo
echo "Odoo is starting."
echo "Web UI:       http://localhost:8069"
echo "Longpolling:  http://localhost:8072"
echo "PostgreSQL:   localhost:5432"
echo "Master pwd:   admin"
echo "Admin login:  admin"
echo "Admin pwd:    admin"
