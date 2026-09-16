#!/usr/bin/env bash
set -euo pipefail
umask 077

INSTALL_DIR=/opt/PalworldGuildSync
SAVE_TOOLS_DIR=${SAVE_TOOLS_DIR:-/opt/PalworldSaveTools}
VENV_DIR="$INSTALL_DIR/.venv"
ENV_FILE="$INSTALL_DIR/.env"
LOCK_FILE=/run/lock/palworld-guild-sync.lock

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

if (( EUID != 0 )); then
  die 'run this installer as root'
fi

command -v python3 >/dev/null || die 'python3 is required'
command -v install >/dev/null || die 'install is required'

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ -f "$SOURCE_DIR/guild_sync.py" ]] || die "missing source in $SOURCE_DIR"
[[ -d "$SAVE_TOOLS_DIR/src/palsav" ]] || die "missing PalworldSaveTools source at $SAVE_TOOLS_DIR"
[[ -d "$SAVE_TOOLS_DIR/src/palsav/palooz" ]] || die "missing palooz source at $SAVE_TOOLS_DIR/src/palsav/palooz"

install -d -m 0755 "$INSTALL_DIR" /run/lock /etc/cron.d /etc/logrotate.d
exec 9>"$LOCK_FILE"
flock 9

install -m 0644 "$SOURCE_DIR/guild_sync.py" "$INSTALL_DIR/guild_sync.py"
install -m 0644 "$SOURCE_DIR/requirements.in" "$INSTALL_DIR/requirements.in"
install -m 0644 "$SOURCE_DIR/requirements.txt" "$INSTALL_DIR/requirements.txt"
install -m 0644 "$SOURCE_DIR/README.md" "$INSTALL_DIR/README.md"
install -m 0644 "$SOURCE_DIR/.env.example" "$INSTALL_DIR/.env.example"
install -m 0755 "$SOURCE_DIR/guild_sync_cron.sh" "$INSTALL_DIR/guild_sync_cron.sh"
install -m 0755 "$SOURCE_DIR/backup.sh" "$INSTALL_DIR/backup.sh"
install -m 0755 "$SOURCE_DIR/restore.sh" "$INSTALL_DIR/restore.sh"
install -d -m 0755 "$INSTALL_DIR/tools"
for tool in "$SOURCE_DIR/tools"/*.py; do
  install -m 0755 "$tool" "$INSTALL_DIR/tools/"
done

if [[ ! -e "$ENV_FILE" ]]; then
  install -m 0600 "$SOURCE_DIR/.env.example" "$ENV_FILE"
  printf 'Created %s from .env.example; set SITE_TOKEN, PLAYER_HASH_SECRET and SAVE_PATH before running cron.\n' "$ENV_FILE" >&2
elif [[ ! -f "$ENV_FILE" || -L "$ENV_FILE" ]]; then
  die "$ENV_FILE must be a regular file"
else
  chown root:root "$ENV_FILE"
  chmod 0600 "$ENV_FILE"
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  install -d -m 0755 "$VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install \
  --disable-pip-version-check --no-cache-dir --require-hashes \
  --requirement "$INSTALL_DIR/requirements.txt"

"$VENV_DIR/bin/python" -m pip install \
  --disable-pip-version-check --no-cache-dir --no-deps --no-build-isolation \
  "$SAVE_TOOLS_DIR/src/palsav/palooz" \
  "$SAVE_TOOLS_DIR/src/palsav"

"$VENV_DIR/bin/python" - <<'PY'
import orjson
import palsav
import palooz
import requests

print("GuildSync dependencies ready", requests.__version__, orjson.__version__)
PY

install -m 0644 \
  "$SOURCE_DIR/cron.d/palworld-guild-sync" \
  /etc/cron.d/palworld-guild-sync
install -m 0644 \
  "$SOURCE_DIR/logrotate.d/palworld-guild-sync" \
  /etc/logrotate.d/palworld-guild-sync

printf 'GuildSync installed in %s; verify %s before the first scheduled run.\n' \
  "$INSTALL_DIR" "$ENV_FILE"
