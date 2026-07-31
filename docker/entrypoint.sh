#!/usr/bin/env bash
set -euo pipefail

: "${DJANGO_SECRET_KEY:?DJANGO_SECRET_KEY is required}"
: "${PRIVATE_API_TOKEN:?PRIVATE_API_TOKEN is required}"
: "${PALWORLD_API_URL:?PALWORLD_API_URL is required}"
: "${PALWORLD_API_PASSWORD:?PALWORLD_API_PASSWORD is required}"

mkdir -p "$(dirname "${DATABASE_PATH}")"

python3 web/manage.py migrate --noinput
python3 web/manage.py shell -c \
  "from django.db import connection; c=connection.cursor(); c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA synchronous=NORMAL')" \
  >/dev/null

public_pid=""
private_pid=""
collector_pid=""

shutdown() {
  local pid running
  local pids=("${public_pid}" "${private_pid}" "${collector_pid}")
  for pid in "${pids[@]}"; do
    [[ -n "${pid}" ]] && kill -TERM "${pid}" 2>/dev/null || true
  done
  for _ in {1..30}; do
    running=false
    for pid in "${pids[@]}"; do
      if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
        running=true
      fi
    done
    [[ "${running}" == false ]] && break
    sleep 1
  done
  for pid in "${pids[@]}"; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill -KILL "${pid}" 2>/dev/null || true
    fi
  done
  wait "${public_pid}" "${private_pid}" "${collector_pid}" 2>/dev/null || true
}
trap shutdown TERM INT EXIT

gunicorn palworld_site.ingest_wsgi:application \
  --chdir /app/web \
  --bind "0.0.0.0:${PRIVATE_INTERNAL_PORT}" \
  --workers 1 \
  --threads 1 \
  --timeout 60 \
  --access-logfile - \
  --error-logfile - &
private_pid=$!

python3 web/manage.py runcollector &
collector_pid=$!

gunicorn palworld_site.wsgi:application \
  --chdir /app/web \
  --bind "0.0.0.0:${SITE_INTERNAL_PORT}" \
  --workers "${WEB_WORKERS:-2}" \
  --threads 2 \
  --timeout 30 \
  --access-logfile - \
  --error-logfile - &
public_pid=$!

wait -n "${public_pid}" "${private_pid}" "${collector_pid}"
