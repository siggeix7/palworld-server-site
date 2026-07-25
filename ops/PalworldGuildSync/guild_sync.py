#!/usr/bin/env python3
"""Send guild and base camp data from a Palworld save to the site."""

import os
import sys

import requests
from palsav.io import load_sav
from palsav.paltypes import PALWORLD_CUSTOM_PROPERTIES


SAVE_PATH = os.getenv(
    "SAVE_PATH",
    "/opt/Palworld/palworld/Pal/Saved/SaveGames/0/"
    "36814278E2A240ADB8F57D42AAF739CD/Level.sav",
)
SITE_URL = os.getenv("SITE_URL", "http://10.77.71.50:8081").rstrip("/")
SITE_TOKEN = os.getenv("SITE_TOKEN", "")
VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() == "true"


def to_str(value):
    if value is None:
        return ""
    return str(value)


def parse_guilds(world_data):
    group_map = world_data.get("GroupSaveDataMap", {}).get("value", {})
    guilds = []
    items = group_map.items() if isinstance(group_map, dict) else enumerate(group_map)

    for group_key, group_data in items:
        group_value = group_data.get("value", group_data)
        group_type = (
            group_value.get("GroupType", {}).get("value", {}).get("value", "?")
        )
        if group_type != "EPalGroupType::Guild":
            continue

        raw_data = group_value.get("RawData", {}).get("value", {})
        players = [
            {
                "player_uid": to_str(player.get("player_uid", "")),
                "player_name": to_str(
                    player.get("player_info", {}).get("player_name", "")
                ),
            }
            for player in raw_data.get("players", [])
        ]
        guilds.append(
            {
                "group_id": to_str(raw_data.get("group_id", group_key)),
                "group_name": to_str(raw_data.get("group_name", "")),
                "guild_name": to_str(
                    raw_data.get("guild_name", raw_data.get("group_name", ""))
                ),
                "admin_player_uid": to_str(
                    raw_data.get("admin_player_uid", "")
                ),
                "players": players,
                "base_ids": [to_str(base) for base in raw_data.get("base_ids", [])],
            }
        )

    return guilds


def parse_bases(world_data, guilds):
    player_counts = {
        guild["group_id"]: len(guild["players"])
        for guild in guilds
    }
    base_camps = world_data.get("BaseCampSaveData", {}).get("value", [])
    bases = []

    if not isinstance(base_camps, list):
        return bases

    for item in base_camps:
        key = item.get("key", {})
        key_value = key.get("value", key) if isinstance(key, dict) else key
        value = item.get("value", {})
        raw_data = value.get("RawData", {}).get("value")
        if not isinstance(raw_data, dict):
            continue

        translation = raw_data.get("transform", {}).get("translation", {})
        group_id = to_str(raw_data.get("group_id_belong_to", ""))
        bases.append(
            {
                "base_id": to_str(raw_data.get("id", key_value)),
                "group_id": group_id,
                "location_x": translation.get("x", 0),
                "location_y": translation.get("y", 0),
                "location_z": translation.get("z", 0),
                "area_range": raw_data.get("area_range", 3500),
                "state": raw_data.get("state", -1),
                "player_count": player_counts.get(group_id, 0),
            }
        )

    return bases


def main():
    if not SITE_TOKEN:
        print("SITE_TOKEN is not set", file=sys.stderr)
        return 1

    custom_properties = {
        key: value
        for key, value in PALWORLD_CUSTOM_PROPERTIES.items()
        if "GroupSaveDataMap" in key or "BaseCampSaveData" in key
    }
    save = load_sav(SAVE_PATH, custom_properties=custom_properties)
    world_data = save.properties.get("worldSaveData", {}).get("value", {})
    guilds = parse_guilds(world_data)
    bases = parse_bases(world_data, guilds)

    response = requests.post(
        f"{SITE_URL}/api/v1/guild/ingest",
        json={"guilds": guilds, "bases": bases},
        headers={"Authorization": f"Bearer {SITE_TOKEN}"},
        verify=VERIFY_SSL,
        timeout=15,
    )
    print(
        f"Sent {len(guilds)} guilds and {len(bases)} bases; "
        f"status={response.status_code}"
    )
    if not response.ok:
        print(response.text, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
