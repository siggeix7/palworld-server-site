# Maintenance Tools

- `inspect_save.py`: lists available world datasets and their sizes.
- `inspect_guilds.py`: prints guild membership and owned base IDs.
- `find_bases.py`: prints every base position and owning guild UUID.
- `convert_sav.py`: converts a save to JSON for offline inspection.

All tools read `SAVE_PATH` and default to the same live save used by
`guild_sync.py`. Keep generated output inside `/opt/PalworldGuildSync`; the
directory `.gitignore` excludes it from version control.

Stop the game server and take a backup before using any tool that writes a
save. The tools currently included here are read-only except for writing an
explicit conversion output path.
