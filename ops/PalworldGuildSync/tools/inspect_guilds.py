#!/usr/bin/env python3
"""Print guild members and owned base IDs from a Palworld save."""

import os

from palsav.io import load_sav
from palsav.paltypes import PALWORLD_CUSTOM_PROPERTIES


SAVE_PATH = os.getenv(
    "SAVE_PATH",
    "/opt/Palworld/palworld/Pal/Saved/SaveGames/0/"
    "36814278E2A240ADB8F57D42AAF739CD/Level.sav",
)


def main():
    custom_properties = {
        key: value
        for key, value in PALWORLD_CUSTOM_PROPERTIES.items()
        if "GroupSaveDataMap" in key
    }
    save = load_sav(SAVE_PATH, custom_properties=custom_properties)
    world_data = save.properties.get("worldSaveData", {}).get("value", {})
    group_map = world_data.get("GroupSaveDataMap", {}).get("value", {})
    items = group_map.items() if isinstance(group_map, dict) else enumerate(group_map)

    for _, group_data in items:
        group_value = group_data.get("value", group_data)
        group_type = (
            group_value.get("GroupType", {}).get("value", {}).get("value", "?")
        )
        if group_type != "EPalGroupType::Guild":
            continue
        raw_data = group_value.get("RawData", {}).get("value", {})
        print(f"{raw_data.get('guild_name') or raw_data.get('group_name') or '?'}")
        print(f"  group_id: {raw_data.get('group_id', '?')}")
        print(f"  admin: {raw_data.get('admin_player_uid', '?')}")
        for player in raw_data.get("players", []):
            info = player.get("player_info", {})
            print(f"  player: {info.get('player_name', '?')} ({player.get('player_uid', '?')})")
        for base_id in raw_data.get("base_ids", []):
            print(f"  base: {base_id}")


if __name__ == "__main__":
    main()
