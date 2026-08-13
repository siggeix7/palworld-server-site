#!/usr/bin/env bash
set -euo pipefail

app_database="${APP_DB_NAME:-palworld_site}"
app_user="${APP_DB_USER:-palworld_app}"

if [[ ! "${app_database}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  printf 'Invalid APP_DB_NAME\n' >&2
  exit 1
fi
if [[ ! "${app_user}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  printf 'Invalid APP_DB_USER\n' >&2
  exit 1
fi

app_password="$(<"${APP_DB_PASSWORD_FILE}")"
if [[ -z "${app_password}" ]]; then
  printf 'APP_DB_PASSWORD_FILE is empty\n' >&2
  exit 1
fi

psql --set=ON_ERROR_STOP=1 \
  --username "${POSTGRES_USER}" \
  --dbname "${POSTGRES_DB}" \
  --set=app_database="${app_database}" \
  --set=app_user="${app_user}" \
  --set=app_password="${app_password}" <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'app_user',
  :'app_password'
)
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') \gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'app_database', :'app_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'app_database') \gexec
SQL
