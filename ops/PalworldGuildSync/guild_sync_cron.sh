#!/bin/bash
set -eu

SYNC_DIR=/opt/PalworldGuildSync

set -a
. "$SYNC_DIR/.env"
set +a

exec /usr/bin/flock -n /run/lock/palworld-guild-sync.lock \
  "$SYNC_DIR/.venv/bin/python" "$SYNC_DIR/guild_sync.py" >> /var/log/guild_sync.log 2>&1
