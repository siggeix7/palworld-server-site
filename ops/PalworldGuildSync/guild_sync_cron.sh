#!/bin/bash
set -eu

SYNC_DIR=/opt/PalworldGuildSync

set -a
. "$SYNC_DIR/.env"
set +a

exec /usr/bin/flock -n /run/lock/palworld-guild-sync.lock \
  /usr/bin/python3 "$SYNC_DIR/guild_sync.py" >> /var/log/guild_sync.log 2>&1
