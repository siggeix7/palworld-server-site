#!/usr/bin/env bash
set -euo pipefail
umask 077
IFS=$' \t\n'
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
unset BASH_ENV CDPATH ENV GZIP BZIP2 XZ_OPT ZSTD_CLEVEL TAR_OPTIONS

SYNC_DIR=${SYNC_DIR:-/opt/PalworldGuildSync}
BACKUP_DIR=${BACKUP_DIR:-$SYNC_DIR/backups}
SAVE_PATH_OVERRIDE=
ALLOW_LIVE=false
KEEP=14

usage() {
  cat >&2 <<'EOF'
Usage: backup.sh [--allow-live] [--save-path PATH] [--backup-dir DIR] [--keep COUNT]

Back up Level.sav and its adjacent Players directory. Stop the game server
first; --allow-live is an explicit acknowledgement that the save may change
while it is being archived.
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

assert_no_symlink_components() {
  local path=$1
  local current=/
  local components=${path#/}
  local component
  while [[ -n "$components" ]]; do
    if [[ "$components" == */* ]]; then
      component=${components%%/*}
      components=${components#*/}
    else
      component=$components
      components=
    fi
    [[ -n "$component" && "$component" != . && "$component" != .. ]] || die "invalid path: $path"
    current="$current$component"
    [[ ! -L "$current" ]] || die "path contains a symbolic link: $current"
    current="$current/"
  done
}

assert_root_private_file() {
  local path=$1
  local label=$2
  [[ -f "$path" && ! -L "$path" ]] || die "$label must be a regular file"
  local owner mode
  read -r owner mode < <(stat -c '%u %a' -- "$path")
  [[ "$owner" == 0 && "$mode" == 600 ]] || die "$label must be root-owned with mode 0600"
}

ensure_private_directory() {
  local path=$1
  local label=$2
  [[ "$path" == /* ]] || die "$label must be an absolute path"
  assert_no_symlink_components "$path"
  if [[ ! -e "$path" ]]; then
    install -d -m 0700 -- "$path"
  fi
  [[ -d "$path" && ! -L "$path" ]] || die "$label must be a directory"
  local owner mode
  read -r owner mode < <(stat -c '%u %a' -- "$path")
  [[ "$owner" == 0 ]] || die "$label must be root-owned"
  if (( 8#$mode & 0022 )); then
    die "$label must not be group- or world-writable"
  fi
}

while (($#)); do
  case "$1" in
    --allow-live)
      ALLOW_LIVE=true
      shift
      ;;
    --save-path)
      (($# >= 2)) || die '--save-path requires a value'
      SAVE_PATH_OVERRIDE=$2
      shift 2
      ;;
    --backup-dir)
      (($# >= 2)) || die '--backup-dir requires a value'
      BACKUP_DIR=$2
      shift 2
      ;;
    --keep)
      (($# >= 2)) || die '--keep requires a value'
      KEEP=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      die "unknown option: $1"
      ;;
  esac
done

if (( EUID != 0 )); then
  die 'run this backup as root so the save can be read consistently'
fi
[[ "$KEEP" =~ ^[1-9][0-9]*$ ]] || die '--keep must be a positive integer'
[[ "$SYNC_DIR" == /* ]] || die 'SYNC_DIR must be an absolute path'
assert_no_symlink_components "$SYNC_DIR"

if [[ -L "$SYNC_DIR/.env" ]]; then
  die 'SYNC_DIR/.env must not be a symbolic link'
elif [[ -e "$SYNC_DIR/.env" ]]; then
  assert_root_private_file "$SYNC_DIR/.env" 'SYNC_DIR/.env'
  set -a
  . "$SYNC_DIR/.env"
  set +a
fi
IFS=$' \t\n'
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
unset BASH_ENV CDPATH ENV GZIP BZIP2 XZ_OPT ZSTD_CLEVEL TAR_OPTIONS
if [[ "$SYNC_DIR" != / ]]; then SYNC_DIR=${SYNC_DIR%/}; fi
if [[ "$BACKUP_DIR" != / ]]; then BACKUP_DIR=${BACKUP_DIR%/}; fi
[[ "$SYNC_DIR" == /* ]] || die 'SYNC_DIR must be an absolute path'
assert_no_symlink_components "$SYNC_DIR"

SAVE_PATH=${SAVE_PATH_OVERRIDE:-${SAVE_PATH:-}}
[[ -n "$SAVE_PATH" ]] || die 'SAVE_PATH is not configured'
[[ "$SAVE_PATH" == /*/Level.sav ]] || die 'SAVE_PATH must be an absolute path to Level.sav'
[[ -f "$SAVE_PATH" && ! -L "$SAVE_PATH" ]] || die "missing regular save file: $SAVE_PATH"

SAVE_DIR=${SAVE_PATH%/*}
PLAYERS_DIR=$SAVE_DIR/Players
assert_no_symlink_components "$SAVE_DIR"
[[ -d "$PLAYERS_DIR" && ! -L "$PLAYERS_DIR" ]] || die "missing regular Players directory: $PLAYERS_DIR"
mapfile -t unsafe_entries < <(find "$PLAYERS_DIR" -mindepth 1 ! -type f -print -quit)
((${#unsafe_entries[@]} == 0)) || die "Players contains a non-regular file: ${unsafe_entries[0]}"
mapfile -t hardlinks < <(find "$PLAYERS_DIR" -type f -links +1 -print -quit)
((${#hardlinks[@]} == 0)) || die "Players contains a hard-linked file: ${hardlinks[0]}"

if [[ "$ALLOW_LIVE" != true ]]; then
  die 'stop the game server first, or rerun with --allow-live'
fi

ensure_private_directory "$BACKUP_DIR" 'BACKUP_DIR'
install -d -m 0755 /run/lock
[[ ! -L /run/lock/palworld-guild-sync.lock ]] || die 'global lock must not be a symbolic link'
exec 8>/run/lock/palworld-guild-sync.lock
flock 8

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
archive=$BACKUP_DIR/palworld-save-$timestamp.tar.gz
temporary=$(mktemp "$BACKUP_DIR/.palworld-save.XXXXXX.tar.gz")
checksum_temporary=
cleanup() {
  [[ -z "$temporary" ]] || rm -f -- "$temporary"
  [[ -z "$checksum_temporary" ]] || rm -f -- "$checksum_temporary"
}
trap cleanup EXIT

tar --create --gzip --file="$temporary" --directory="$SAVE_DIR" Level.sav Players
[[ ! -e "$archive" && ! -L "$archive" ]] || die "backup archive already exists: $archive"
mv -- "$temporary" "$archive"
temporary=
chmod 0600 "$archive"
checksum_temporary=$(mktemp "$BACKUP_DIR/.palworld-save.XXXXXX.sha256")
(cd -- "$BACKUP_DIR" && sha256sum -- "$(basename -- "$archive")") >"$checksum_temporary"
chmod 0600 "$checksum_temporary"
mv -- "$checksum_temporary" "$archive.sha256"
checksum_temporary=

shopt -s nullglob
archives=("$BACKUP_DIR"/palworld-save-*.tar.gz)
if ((${#archives[@]} > KEEP)); then
  mapfile -t sorted_archives < <(printf '%s\n' "${archives[@]}" | sort -r)
  for ((index=KEEP; index<${#sorted_archives[@]}; index++)); do
    old_archive=${sorted_archives[index]}
    rm -f -- "$old_archive" "$old_archive.sha256"
  done
fi

printf 'Created %s\n' "$archive"
