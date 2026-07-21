#!/usr/bin/env bash
set -euo pipefail

: "${DJANGO_SECRET_KEY:?DJANGO_SECRET_KEY is required}"
: "${ZABBIX_CONNECTOR_TOKEN:?ZABBIX_CONNECTOR_TOKEN is required}"

mkdir -p "$(dirname "${DATABASE_PATH}")"

python3 web/manage.py migrate --noinput
python3 web/manage.py shell -c \
  "from django.db import connection; c=connection.cursor(); c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA synchronous=NORMAL')" \
  >/dev/null

public_pid=""
ingest_pid=""
watcher_pid=""

shutdown() {
  [[ -n "${public_pid}" ]] && kill -TERM "${public_pid}" 2>/dev/null || true
  [[ -n "${ingest_pid}" ]] && kill -TERM "${ingest_pid}" 2>/dev/null || true
  [[ -n "${watcher_pid}" ]] && kill -TERM "${watcher_pid}" 2>/dev/null || true
  wait "${public_pid}" "${ingest_pid}" "${watcher_pid}" 2>/dev/null || true
}
trap shutdown TERM INT EXIT

gunicorn palworld_site.ingest_wsgi:application \
  --chdir /app/web \
  --bind "0.0.0.0:${INGEST_INTERNAL_PORT}" \
  --workers 1 \
  --threads 1 \
  --timeout 30 \
  --access-logfile - \
  --error-logfile - &
ingest_pid=$!

gunicorn palworld_site.wsgi:application \
  --chdir /app/web \
  --bind "0.0.0.0:${SITE_INTERNAL_PORT}" \
  --workers "${WEB_WORKERS:-2}" \
  --threads 2 \
  --timeout 30 \
  --access-logfile - \
  --error-logfile - &
public_pid=$!

if [[ -n "${PALWORLD_API_URL:-}" && -n "${PALWORLD_API_PASSWORD:-}" ]]; then
  python3 web/manage.py watch_players &
  watcher_pid=$!
fi

wait -n "${public_pid}" "${ingest_pid}" "${watcher_pid}"
