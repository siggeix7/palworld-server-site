# Palworld Guild Sync

This directory is the repository source for `/opt/PalworldGuildSync` on
`VM-PALWORLD`. The scheduled job parses `Level.sav` and sends guild and base
camp data to the site's ingest service.

## Install

1. Install `PalworldSaveTools`/`palsav-flex` and `requests` on the Palworld VM.
2. Copy this directory to `/opt/PalworldGuildSync`.
3. Copy `.env.example` to `.env`, set the real token, and run
   `chmod 600 /opt/PalworldGuildSync/.env`.
4. Make `guild_sync.py` and `guild_sync_cron.sh` executable.
5. Add this crontab entry:

```cron
*/5 * * * * /opt/PalworldGuildSync/guild_sync_cron.sh
```

Run a manual synchronization with:

```bash
/opt/PalworldGuildSync/guild_sync_cron.sh
```

## Repository Policy

The live `.env`, converted saves, JSON dumps, backups, and downloaded tool
archives must not be committed. The scripts under `tools/` are maintenance
utilities and are not called by cron.

The save currently exposes useful data including guilds, base camps, PalBox
objects and health, characters/Pals, dungeons, enemy camps, items, and world
time. Only guilds and base positions are uploaded by the scheduled job.
