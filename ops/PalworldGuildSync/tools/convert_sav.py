#!/usr/bin/env python3
"""Convert Level.sav to JSON for offline inspection."""

import argparse
import json

from palsav.io import load_sav
from palsav.json_tools import CustomEncoder


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input Level.sav path")
    parser.add_argument("output", help="Output JSON path")
    args = parser.parse_args()

    save = load_sav(args.input)
    document = {
        "header": {
            "magic": save.header.magic.hex(),
            "save_game_version": save.header.save_game_version,
            "save_package_version": save.header.save_package_version,
            "engine_version_major": save.header.engine_version_major,
            "engine_version_minor": save.header.engine_version_minor,
            "engine_version_patch": save.header.engine_version_patch,
            "engine_version_build": save.header.engine_version_build,
            "engine_version_branch": save.header.engine_version_branch,
            "custom_version_format": save.header.custom_version_format,
            "custom_versions": save.header.custom_versions,
            "save_game_class_name": save.header.save_game_class_name,
        },
        "properties": save.properties,
        "trailer": save.trailer.hex(),
    }
    with open(args.output, "w", encoding="utf-8") as output:
        json.dump(document, output, cls=CustomEncoder, indent=2)


if __name__ == "__main__":
    main()
