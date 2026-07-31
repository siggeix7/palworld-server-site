# Palworld Guild Sync

This directory is the repository source for `/opt/PalworldGuildSync` on
`VM-PALWORLD`. The scheduled job parses `Level.sav` and sends compact guild,
base camp, historical player, and world-status data to the site's ingest service.

## Install

1. Install the source archive for
   [`PalworldSaveTools v2.1.7`](https://github.com/deafdudecomputers/PalworldSaveTools/releases/tag/v2.1.7)
   under `/opt/PalworldSaveTools`. The expected source archive SHA-256 is
   `988dc766a903fa9ef56d172ecd2bee5b77c4920123f7dccc6084ee251c68b2e3`.
   Install its local `palsav-flex 0.2.0` and `palooz 0.2.0` packages; they are
   not published on PyPI.
2. Create `/opt/PalworldGuildSync/.venv` and install the local parser packages
   and this directory's requirements into that virtual environment.
3. Copy this directory to `/opt/PalworldGuildSync` without replacing `.env`.
4. Copy `.env.example` to `.env`, set the real token, and run
    `chmod 600 /opt/PalworldGuildSync/.env`.
   Prefer an HTTPS endpoint with `VERIFY_SSL=true`. HTTP requires
   `ALLOW_INSECURE_HTTP=true` and must remain confined to a trusted LAN or VPN.
5. Make `guild_sync.py` and `guild_sync_cron.sh` executable.
6. Add this crontab entry:

```cron
*/5 * * * * /opt/PalworldGuildSync/guild_sync_cron.sh
```

Run a manual synchronization with:

```bash
/opt/PalworldGuildSync/guild_sync_cron.sh
```

## Repository Policy

The live `.env`, converted saves, JSON dumps, backups, and downloaded tool
archives must not be committed. The scripts under `tools/` consolidate the
old inspection/conversion experiments and are not called by cron. One-off
save mutation scripts are intentionally not tracked because they contained
live player/base UUIDs and were specific to a completed migration.

The scheduled job uploads compact aggregates for guilds, bases, workers,
player progression, active invasions, and oil-rig state. Historical players
come from `Level.sav`, independently of website registration. Raw save UUIDs
are replaced with opaque join keys. Individual Pal records, inventories,
structures, health values, and technical save references remain on the
Palworld VM and are not exposed by the site.
