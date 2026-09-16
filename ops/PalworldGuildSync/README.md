# Palworld Guild Sync

This directory is the repository source for `/opt/PalworldGuildSync` on
`VM-PALWORLD`. The scheduled job parses `Level.sav` and the adjacent
`Players/*.sav` files, then sends compact public guild, base camp, historical
player, and world-status data plus separately stored private claim material to
the site's ingest service.

## Install

1. Install the source archive for
   [`PalworldSaveTools v2.1.7`](https://github.com/deafdudecomputers/PalworldSaveTools/releases/tag/v2.1.7)
   under `/opt/PalworldSaveTools`. The expected source archive SHA-256 is
   `988dc766a903fa9ef56d172ecd2bee5b77c4920123f7dccc6084ee251c68b2e3`.
   Install its local `palsav-flex 0.2.0` and `palooz 0.2.0` packages; they are
   not published on PyPI.
2. From this checkout, run the installer as root. It creates the virtual
   environment, installs the hash-locked requirements and local parser packages,
   and installs the cron and logrotate entries:

   ```bash
   SAVE_TOOLS_DIR=/opt/PalworldSaveTools ./install.sh
   ```

   The installer copies the tracked files to `/opt/PalworldGuildSync` without
   replacing an existing `.env`. It creates `.env` from the example on a new
   install and reports that it still needs configuration.
3. Set the real token and the same `PLAYER_HASH_SECRET` used by the site in
   `/opt/PalworldGuildSync/.env`, and run
     `chmod 600 /opt/PalworldGuildSync/.env`.
   Prefer an HTTPS endpoint with `VERIFY_SSL=true`. HTTP requires
   `ALLOW_INSECURE_HTTP=true` and must remain confined to a trusted LAN or VPN.
   Prefer `PLAYER_HASH_SECRET_FILE` over putting the shared secret in `.env`.
4. Confirm that `SAVE_PATH` points to `Level.sav`; the collector discovers the
   sibling `Players` directory automatically and excludes `*_dps.sav` files.
   The installer configures this schedule in `/etc/cron.d/palworld-guild-sync`:

```cron
*/5 * * * * root /opt/PalworldGuildSync/guild_sync_cron.sh
```

Run a manual synchronization with:

```bash
/opt/PalworldGuildSync/guild_sync_cron.sh
```

The job serializes installs and syncs with `/run/lock/palworld-guild-sync.lock`.
Its log is `/var/log/guild_sync.log` and is rotated daily, retaining 14
compressed rotations.

## Save Backups

The backup contains `Level.sav` and the adjacent `Players` directory, but never
the GuildSync `.env`. Stop the game server before creating a consistent backup;
the explicit flag acknowledges that the save state was checked:

```bash
/opt/PalworldGuildSync/backup.sh --allow-live
```

Backups and SHA-256 sidecars are stored with mode `0600` under
`/opt/PalworldGuildSync/backups`, with the newest 14 archives retained. Restore
only while the game server is stopped and use the explicit confirmation flag:

```bash
/opt/PalworldGuildSync/restore.sh \
  --archive /opt/PalworldGuildSync/backups/palworld-save-<timestamp>.tar.gz \
  --confirm
```

Restore verifies the sidecar checksum, rejects unexpected archive paths and
symbolic links, and creates a pre-restore rollback archive before replacement.

## Repository Policy

The live `.env`, converted saves, JSON dumps, backups, and downloaded tool
archives must not be committed. The scripts under `tools/` consolidate the
old inspection/conversion experiments and are not called by cron. One-off
save mutation scripts are intentionally not tracked because they contained
live player/base UUIDs and were specific to a completed migration.

The scheduled job uploads compact aggregates for guilds, bases, workers, player
progression, active invasions, and oil-rig state. Historical players come from
`Level.sav`, independently of website registration. Schema 4 additionally sends
validated inventory stacks, party references, and seven private progress maps;
the private listener stores those claim fields separately from the public
snapshot. Raw save UUIDs are replaced with opaque public join keys and are never
returned in public map or roster responses. Claim data is available only through
the no-store verification/progress flow.
