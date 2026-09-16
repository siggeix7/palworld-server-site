#!/usr/bin/env bash
set -euo pipefail
umask 077
IFS=$' \t\n'
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
unset BASH_ENV CDPATH ENV GZIP BZIP2 XZ_OPT ZSTD_CLEVEL TAR_OPTIONS PYTHONHOME PYTHONPATH PYTHONSTARTUP

SYNC_DIR=${SYNC_DIR:-/opt/PalworldGuildSync}
BACKUP_DIR=${BACKUP_DIR:-$SYNC_DIR/backups}
ARCHIVE=
SAVE_PATH_OVERRIDE=
CONFIRM=false
ROLLBACK_KEEP=14

usage() {
  cat >&2 <<'EOF'
Usage: restore.sh --archive FILE --confirm [--save-path PATH] [--backup-dir DIR]

Restore Level.sav and Players from a backup. Stop the game server first. The
current save is copied to a timestamped rollback archive before replacement.
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
    --archive)
      (($# >= 2)) || die '--archive requires a value'
      ARCHIVE=$2
      shift 2
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
    --confirm)
      CONFIRM=true
      shift
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
  die 'run this restore as root'
fi
[[ "$CONFIRM" == true ]] || die '--confirm is required'
[[ -n "$ARCHIVE" ]] || die '--archive is required'
if [[ "$ARCHIVE" != /* ]]; then
  ARCHIVE=$(pwd -P)/$ARCHIVE
fi
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
unset BASH_ENV CDPATH ENV GZIP BZIP2 XZ_OPT ZSTD_CLEVEL TAR_OPTIONS PYTHONHOME PYTHONPATH PYTHONSTARTUP
if [[ "$SYNC_DIR" != / ]]; then SYNC_DIR=${SYNC_DIR%/}; fi
if [[ "$BACKUP_DIR" != / ]]; then BACKUP_DIR=${BACKUP_DIR%/}; fi
[[ "$SYNC_DIR" == /* ]] || die 'SYNC_DIR must be an absolute path'
assert_no_symlink_components "$SYNC_DIR"

SAVE_PATH=${SAVE_PATH_OVERRIDE:-${SAVE_PATH:-}}
[[ -n "$SAVE_PATH" ]] || die 'SAVE_PATH is not configured'
[[ "$SAVE_PATH" == /*/Level.sav ]] || die 'SAVE_PATH must be an absolute path to Level.sav'
SAVE_DIR=${SAVE_PATH%/*}
PLAYERS_DIR=$SAVE_DIR/Players
assert_no_symlink_components "$SAVE_DIR"
[[ ! -e "$SAVE_PATH" || ( -f "$SAVE_PATH" && ! -L "$SAVE_PATH" ) ]] \
  || die 'SAVE_PATH must be a regular file or not exist'
[[ ! -e "$PLAYERS_DIR" || ( -d "$PLAYERS_DIR" && ! -L "$PLAYERS_DIR" ) ]] \
  || die 'Players must be a directory or not exist'

[[ "$BACKUP_DIR" == /* ]] || die 'BACKUP_DIR must be an absolute path'
ensure_private_directory "$BACKUP_DIR" 'BACKUP_DIR'
install -d -m 0755 /run/lock
[[ ! -L /run/lock/palworld-guild-sync.lock ]] || die 'global lock must not be a symbolic link'
exec 8>/run/lock/palworld-guild-sync.lock
flock 8

checksum_file=$ARCHIVE.sha256
archive_dir=$(dirname -- "$ARCHIVE")
[[ "$archive_dir" == "$BACKUP_DIR" ]] || die 'archive must be inside BACKUP_DIR'
assert_no_symlink_components "$archive_dir"
assert_root_private_file "$ARCHIVE" 'archive'
assert_root_private_file "$checksum_file" 'archive checksum'
read -r expected_hash expected_name <"$checksum_file" || die 'invalid checksum file'
[[ "$expected_hash" =~ ^[[:xdigit:]]{64}$ ]] || die 'invalid archive checksum'
[[ "$expected_name" == "$(basename -- "$ARCHIVE")" ]] || die 'checksum is for a different archive'
(cd -- "$(dirname -- "$ARCHIVE")" && sha256sum --check --status "$(basename -- "$checksum_file")") \
  || die 'archive checksum failed'

[[ -d "$SAVE_DIR" ]] || install -d -m 0700 -- "$SAVE_DIR"
assert_no_symlink_components "$SAVE_DIR"
rollback_archive=$BACKUP_DIR/palworld-pre-restore-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz
[[ ! -e "$rollback_archive" && ! -L "$rollback_archive" ]] \
  || die 'rollback archive already exists'
[[ ! -e "$rollback_archive.sha256" && ! -L "$rollback_archive.sha256" ]] \
  || die 'rollback checksum already exists'
staging=$(mktemp -d "$SAVE_DIR/.palworld-restore.XXXXXX")
rollback_dir=$(mktemp -d "$SAVE_DIR/.palworld-rollback.XXXXXX")
rollback_temporary=
checksum_temporary=
transaction_started=false
save_staged=false
players_staged=false

save_owner=$(stat -c '%u:%g' "$SAVE_PATH" 2>/dev/null || stat -c '%u:%g' "$SAVE_DIR")
players_owner=$(stat -c '%u:%g' "$PLAYERS_DIR" 2>/dev/null || printf '%s' "$save_owner")
save_mode=$(stat -c '%a' "$SAVE_PATH" 2>/dev/null || printf '0600')
players_mode=$(stat -c '%a' "$PLAYERS_DIR" 2>/dev/null || printf '0700')

cleanup() {
  status=$?
  if [[ "$transaction_started" == true && $status -ne 0 ]]; then
    if [[ "$save_staged" == true ]]; then
      rm -rf -- "$SAVE_PATH"
      [[ ! -e "$rollback_dir/Level.sav" ]] || mv -- "$rollback_dir/Level.sav" "$SAVE_PATH"
    fi
    if [[ "$players_staged" == true ]]; then
      rm -rf -- "$PLAYERS_DIR"
      [[ ! -e "$rollback_dir/Players" ]] || mv -- "$rollback_dir/Players" "$PLAYERS_DIR"
    fi
    printf 'restore failed; previous save was put back\n' >&2
  fi
  [[ -z "$rollback_temporary" ]] || rm -f -- "$rollback_temporary"
  [[ -z "$checksum_temporary" ]] || rm -f -- "$checksum_temporary"
  rm -rf -- "$staging" "$rollback_dir"
  exit "$status"
}
trap cleanup EXIT

command -v python3 >/dev/null || die 'python3 is required to inspect the archive'
if ! python3 - "$ARCHIVE" "$staging" <<'PY'
import os
import shutil
import sys
import tarfile

archive_path, staging = sys.argv[1:]
max_members = 8192
max_member_size = 512 * 1024 * 1024
max_total_size = 2 * 1024 * 1024 * 1024
allowed_files = {"Level.sav"}
seen = set()
total_size = 0

try:
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError("archive is empty")
        if len(members) > max_members:
            raise ValueError("archive contains too many entries")
        for member in members:
            name = member.name
            if name in seen:
                raise ValueError(f"archive repeats a path: {name}")
            seen.add(name)
            if name in {"Players", "Players/"}:
                if not member.isdir():
                    raise ValueError("archive Players entry is not a directory")
                continue
            if name not in allowed_files and not (
                name.startswith("Players/")
                and name.count("/") == 1
                and name.endswith(".sav")
            ):
                raise ValueError(f"archive contains an unexpected path: {name}")
            if not member.isreg():
                raise ValueError(f"archive contains a non-regular file: {name}")
            if member.size < 0 or member.size > max_member_size:
                raise ValueError(f"archive file is too large: {name}")
            total_size += member.size
            if total_size > max_total_size:
                raise ValueError("archive expands beyond the configured size limit")

        if "Level.sav" not in seen or not any(name in seen for name in ("Players", "Players/")):
            raise ValueError("archive must contain Level.sav and Players")

        os.makedirs(os.path.join(staging, "Players"), mode=0o700, exist_ok=True)
        for member in members:
            if member.name in {"Players", "Players/"}:
                continue
            destination = os.path.join(staging, member.name)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"archive file cannot be read: {member.name}")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            with source, os.fdopen(os.open(destination, flags, 0o600), "wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            os.chmod(destination, 0o600)
except (OSError, tarfile.TarError, ValueError) as exc:
    print(f"error: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
then
  die 'archive validation or extraction failed'
fi
[[ -f "$staging/Level.sav" && ! -L "$staging/Level.sav" ]] || die 'archive has no regular Level.sav'
[[ -d "$staging/Players" && ! -L "$staging/Players" ]] || die 'archive has no regular Players directory'

if [[ -f "$SAVE_PATH" && ! -L "$SAVE_PATH" && -d "$PLAYERS_DIR" && ! -L "$PLAYERS_DIR" ]]; then
  mapfile -t current_unsafe < <(find "$PLAYERS_DIR" -mindepth 1 ! -type f -print -quit)
  ((${#current_unsafe[@]} == 0)) || die "current Players contains a non-regular file: ${current_unsafe[0]}"
  mapfile -t current_hardlinks < <(find "$PLAYERS_DIR" -type f -links +1 -print -quit)
  ((${#current_hardlinks[@]} == 0)) || die "current Players contains a hard-linked file: ${current_hardlinks[0]}"
  rollback_temporary=$(mktemp "$BACKUP_DIR/.palworld-pre-restore.XXXXXX.tar.gz")
  tar --create --gzip --file="$rollback_temporary" --directory="$SAVE_DIR" Level.sav Players
  chmod 0600 "$rollback_temporary"
  mv -- "$rollback_temporary" "$rollback_archive"
  rollback_temporary=
  checksum_temporary=$(mktemp "$BACKUP_DIR/.palworld-pre-restore.XXXXXX.sha256")
  (cd -- "$BACKUP_DIR" && sha256sum -- "$(basename -- "$rollback_archive")") \
    >"$checksum_temporary"
  chmod 0600 "$checksum_temporary"
  mv -- "$checksum_temporary" "$rollback_archive.sha256"
  checksum_temporary=
fi

transaction_started=true
if [[ -e "$SAVE_PATH" ]]; then mv -- "$SAVE_PATH" "$rollback_dir/Level.sav"; fi
save_staged=true
if [[ -e "$PLAYERS_DIR" ]]; then mv -- "$PLAYERS_DIR" "$rollback_dir/Players"; fi
players_staged=true
mv -- "$staging/Level.sav" "$SAVE_PATH"
mv -- "$staging/Players" "$PLAYERS_DIR"
chown "$save_owner" "$SAVE_PATH"
chown -R "$players_owner" "$PLAYERS_DIR"
chmod "$save_mode" "$SAVE_PATH"
chmod "$players_mode" "$PLAYERS_DIR"
transaction_started=false

shopt -s nullglob
rollback_archives=("$BACKUP_DIR"/palworld-pre-restore-*.tar.gz)
if ((${#rollback_archives[@]} > ROLLBACK_KEEP)); then
  mapfile -t sorted_rollbacks < <(printf '%s\n' "${rollback_archives[@]}" | sort -r)
  for ((index=ROLLBACK_KEEP; index<${#sorted_rollbacks[@]}; index++)); do
    old_rollback=${sorted_rollbacks[index]}
    rm -f -- "$old_rollback" "$old_rollback.sha256"
  done
fi

printf 'Restored %s to %s\n' "$ARCHIVE" "$SAVE_PATH"
[[ ! -f "$rollback_archive" ]] || printf 'Rollback archive: %s\n' "$rollback_archive"
