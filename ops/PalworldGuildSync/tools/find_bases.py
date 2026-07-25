#!/usr/bin/env python3
"""Print base camp positions and owning guild UUIDs."""

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
        if "BaseCampSaveData" in key
    }
    save = load_sav(SAVE_PATH, custom_properties=custom_properties)
    world_data = save.properties.get("worldSaveData", {}).get("value", {})
    base_camps = world_data.get("BaseCampSaveData", {}).get("value", [])

    for item in base_camps if isinstance(base_camps, list) else []:
        raw_data = item.get("value", {}).get("RawData", {}).get("value", {})
        translation = raw_data.get("transform", {}).get("translation", {})
        print(raw_data.get("id", item.get("key", "?")))
        print(f"  guild: {raw_data.get('group_id_belong_to', '?')}")
        print(
            "  location: "
            f"X={translation.get('x', 0)} "
            f"Y={translation.get('y', 0)} "
            f"Z={translation.get('z', 0)}"
        )
        print(f"  area_range: {raw_data.get('area_range', '?')}")


if __name__ == "__main__":
    main()
