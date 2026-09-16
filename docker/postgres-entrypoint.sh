#!/usr/bin/env bash
set -Eeuo pipefail

upstream=/usr/local/bin/docker-entrypoint.sh
child_pid=

forward_signal() {
  [[ -z "$child_pid" ]] || kill -TERM "$child_pid" 2>/dev/null || true
}
trap forward_signal TERM INT

if [[ "${1:-}" != "postgres" ]]; then
  exec "$upstream" "$@"
fi

: "${POSTGRES_PASSWORD_FILE:?POSTGRES_PASSWORD_FILE is required}"
: "${APP_DB_PASSWORD_FILE:?APP_DB_PASSWORD_FILE is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${APP_DB_NAME:?APP_DB_NAME is required}"
: "${APP_DB_USER:?APP_DB_USER is required}"

data_directory=${PGDATA:-/var/lib/postgresql/data}
if [[ ! -f "$data_directory/PG_VERSION" ]]; then
  # The official entrypoint runs init scripts against a temporary server. Let
  # it finish first; postgres-init.sh sets the initial application password.
  exec "$upstream" "$@"
fi

admin_password=$(<"$POSTGRES_PASSWORD_FILE")
app_password=$(<"$APP_DB_PASSWORD_FILE")
[[ -n "$admin_password" ]] || { printf 'POSTGRES_PASSWORD_FILE is empty\n' >&2; exit 1; }
[[ -n "$app_password" ]] || { printf 'APP_DB_PASSWORD_FILE is empty\n' >&2; exit 1; }

"$upstream" "$@" &
child_pid=$!

ready=false
for _ in {1..60}; do
  if ! kill -0 "$child_pid" 2>/dev/null; then
    wait "$child_pid"
    exit 1
  fi
  if pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done

if [[ "$ready" != true ]]; then
  printf 'PostgreSQL did not become ready for password synchronization\n' >&2
  kill -TERM "$child_pid" 2>/dev/null || true
  wait "$child_pid" 2>/dev/null || true
  exit 1
fi

if ! APP_DB_PASSWORD="$app_password" PGPASSWORD="$admin_password" psql \
  --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=app_database="$APP_DB_NAME" \
  --set=app_user="$APP_DB_USER" <<'SQL'
\getenv app_password APP_DB_PASSWORD
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'app_user',
  :'app_password'
)
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') \gexec

SELECT format('ALTER ROLE %I PASSWORD %L', :'app_user', :'app_password')
WHERE EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') \gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'app_database', :'app_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'app_database') \gexec
SQL
then
  printf 'Unable to synchronize the PostgreSQL application password\n' >&2
  kill -TERM "$child_pid" 2>/dev/null || true
  wait "$child_pid" 2>/dev/null || true
  exit 1
fi

unset admin_password app_password
wait "$child_pid"
