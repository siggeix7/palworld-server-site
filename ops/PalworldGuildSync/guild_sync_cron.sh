#!/usr/bin/env bash
set -euo pipefail
umask 077

SYNC_DIR=/opt/PalworldGuildSync
LOCK_FILE=/run/lock/palworld-guild-sync.lock
LOG_FILE=/var/log/guild_sync.log

if [[ ! -f "$SYNC_DIR/.env" || -L "$SYNC_DIR/.env" ]]; then
  printf 'Missing %s/.env\n' "$SYNC_DIR" >&2
  exit 1
fi
if [[ "$(stat -c '%u %a' "$SYNC_DIR/.env")" != '0 600' ]]; then
  printf '%s/.env must be owned by root with mode 0600\n' "$SYNC_DIR" >&2
  exit 1
fi

install -d -m 0755 /run/lock
if [[ -L "$LOCK_FILE" ]]; then
  printf '%s must not be a symbolic link\n' "$LOCK_FILE" >&2
  exit 1
fi
exec 9>"$LOCK_FILE"
flock -n 9 || exit 0

set -a
. "$SYNC_DIR/.env"
set +a
IFS=$' \t\n'
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
unset BASH_ENV CDPATH ENV GZIP BZIP2 XZ_OPT ZSTD_CLEVEL TAR_OPTIONS PYTHONHOME PYTHONPATH PYTHONSTARTUP

if [[ ! -x "$SYNC_DIR/.venv/bin/python" ]]; then
  printf 'Missing GuildSync virtualenv at %s/.venv\n' "$SYNC_DIR" >&2
  exit 1
fi

exec "$SYNC_DIR/.venv/bin/python" "$SYNC_DIR/guild_sync.py" >>"$LOG_FILE" 2>&1
