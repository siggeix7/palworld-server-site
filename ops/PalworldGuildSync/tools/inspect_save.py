#!/usr/bin/env python3
"""List the datasets present in a Palworld Level.sav file."""

import os

from palsav.io import load_sav


SAVE_PATH = os.getenv(
    "SAVE_PATH",
    "/opt/Palworld/palworld/Pal/Saved/SaveGames/0/"
    "36814278E2A240ADB8F57D42AAF739CD/Level.sav",
)


def main():
    save = load_sav(SAVE_PATH)
    world_data = save.properties.get("worldSaveData", {}).get("value", {})
    for name in sorted(world_data):
        value = world_data[name].get("value", world_data[name])
        size = len(value) if hasattr(value, "__len__") else "-"
        print(f"{name}: {type(value).__name__} ({size})")


if __name__ == "__main__":
    main()
