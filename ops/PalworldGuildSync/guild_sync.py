#!/usr/bin/env python3
"""Send compact guild, base camp, and world data to the site."""

from collections import Counter, defaultdict
import hashlib
import os
import sys

import requests


SAVE_PATH = os.getenv(
    "SAVE_PATH",
    "/opt/Palworld/palworld/Pal/Saved/SaveGames/0/"
    "36814278E2A240ADB8F57D42AAF739CD/Level.sav",
)
SITE_URL = os.getenv("SITE_URL", "http://10.77.71.50:8081").rstrip("/")
SITE_TOKEN = os.getenv("SITE_TOKEN", "")
VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() == "true"
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
LOW_SANITY_THRESHOLD = 30


def to_str(value):
    if value is None:
        return ""
    return str(value)


def property_value(value, default=None):
    while isinstance(value, dict) and "value" in value:
        value = value["value"]
    return default if value is None else value


def property_number(properties, name):
    value = property_value(properties.get(name))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def enum_name(properties, name):
    value = property_value(properties.get(name), "")
    suffix = to_str(value).rsplit("::", 1)[-1] if value else ""
    return "" if suffix.casefold() in {"none", "invalid"} else suffix


def base_name(value, ordinal):
    name = to_str(value).strip()
    if not name or name.startswith("\u65b0\u898f\u751f\u6210"):
        return f"Base {ordinal}"
    return name[:128]


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
        admin_player_uid = to_str(raw_data.get("admin_player_uid", ""))
        players = []
        for player in raw_data.get("players", []):
            player_uid = to_str(player.get("player_uid", ""))
            players.append({
                "player_uid": player_uid,
                "player_name": to_str(
                    player.get("player_info", {}).get("player_name", "")
                ),
                "is_admin": player_uid == admin_player_uid,
            })
        guilds.append(
            {
                "group_id": to_str(raw_data.get("group_id", group_key)),
                "guild_name": to_str(raw_data.get("guild_name", "")),
                "admin_player_uid": admin_player_uid,
                "players": players,
                "base_ids": [to_str(base) for base in raw_data.get("base_ids", [])],
            }
        )

    return guilds


def index_characters(world_data, guilds):
    # Saved guild handle lists retain historical memberships after transfers.
    # Current owners plus base worker containers provide the active attribution.
    player_guilds = {
        player["player_uid"]: guild["group_id"]
        for guild in guilds
        for player in guild["players"]
    }
    guild_pal_ids = {guild["group_id"]: set() for guild in guilds}
    characters = {}

    for item in world_data.get("CharacterSaveParameterMap", {}).get("value", []):
        key = item.get("key", {})
        instance_id = to_str(property_value(key.get("InstanceId"), ""))
        if not instance_id or instance_id == ZERO_UUID:
            continue
        raw_data = item.get("value", {}).get("RawData", {}).get("value", {})
        save_parameters = (
            raw_data.get("object", {}).get("SaveParameter", {}).get("value", {})
        )
        if property_value(save_parameters.get("IsPlayer"), False):
            continue
        characters[instance_id] = save_parameters
        owner_id = to_str(property_value(save_parameters.get("OwnerPlayerUId"), ""))
        guild_id = player_guilds.get(owner_id)
        if guild_id:
            guild_pal_ids[guild_id].add(instance_id)

    return characters, guild_pal_ids


def index_character_containers(world_data):
    containers = {}
    for item in world_data.get("CharacterContainerSaveData", {}).get("value", []):
        key = item.get("key", {})
        container_id = to_str(property_value(key.get("ID"), ""))
        if not container_id or container_id == ZERO_UUID:
            continue
        slots = (
            item.get("value", {})
            .get("Slots", {})
            .get("value", {})
            .get("values", [])
        )
        instance_ids = set()
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            slot_data = slot.get("RawData", {}).get("value")
            if isinstance(slot_data, dict):
                instance_ids.add(to_str(slot_data.get("instance_id", "")))
        containers[container_id] = instance_ids - {"", ZERO_UUID}
    return containers


def parse_world(world_data):
    active_raid_base_ids = set()
    invaders = world_data.get("InvaderSaveData", {}).get("value", [])
    for item in invaders if isinstance(invaders, list) else []:
        if property_value(item.get("value", {}).get("bIsInvading"), False):
            active_raid_base_ids.add(to_str(item.get("key", "")))

    oil_rigs = (
        world_data.get("OilrigSaveData", {})
        .get("value", {})
        .get("OilrigMap", {})
        .get("value", [])
    )
    if not isinstance(oil_rigs, list):
        oil_rigs = []
    oil_rig_entries = [
        item
        for item in oil_rigs
        if not to_str(item.get("key", "")).endswith("::Debug")
    ]
    return {
        "active_raid_count": len(active_raid_base_ids),
        "oil_rig_count": len(oil_rig_entries),
        "oil_rig_alert_count": sum(
            bool(property_value(item.get("value", {}).get("Alarm"), False))
            for item in oil_rig_entries
        ),
        "oil_rig_cleared_count": sum(
            bool(property_value(item.get("value", {}).get("Clear"), False))
            for item in oil_rig_entries
        ),
    }, active_raid_base_ids


def parse_bases(
    world_data,
    guilds,
    characters,
    containers,
    guild_pal_ids,
    active_raid_base_ids,
):
    player_counts = {
        guild["group_id"]: len(guild["players"])
        for guild in guilds
    }
    guild_ids = set(player_counts)
    guild_workers = defaultdict(set)
    guild_working = defaultdict(set)
    guild_problems = defaultdict(set)
    base_ordinals = Counter()
    base_camps = world_data.get("BaseCampSaveData", {}).get("value", [])
    bases = []
    diagnostics = {
        "unowned_base_count": 0,
        "missing_worker_container_count": 0,
        "unresolved_worker_count": 0,
    }

    if not isinstance(base_camps, list):
        return bases, diagnostics, guild_workers, guild_working, guild_problems

    for item in base_camps:
        key = item.get("key", {})
        key_value = key.get("value", key) if isinstance(key, dict) else key
        value = item.get("value", {})
        raw_data = value.get("RawData", {}).get("value")
        if not isinstance(raw_data, dict):
            continue

        translation = raw_data.get("transform", {}).get("translation", {})
        base_id = to_str(raw_data.get("id", key_value))
        group_id = to_str(raw_data.get("group_id_belong_to", ""))
        base_ordinals[group_id] += 1
        if group_id not in guild_ids:
            diagnostics["unowned_base_count"] += 1

        director = (
            value.get("WorkerDirector", {})
            .get("value", {})
            .get("RawData", {})
            .get("value", {})
        )
        container_id = to_str(director.get("container_id", ""))
        if container_id and container_id not in containers:
            diagnostics["missing_worker_container_count"] += 1
        worker_ids = containers.get(container_id, set())
        resolved_worker_ids = worker_ids & characters.keys()
        diagnostics["unresolved_worker_count"] += len(worker_ids - characters.keys())

        sick_ids = set()
        hungry_ids = set()
        low_sanity_ids = set()
        working_ids = set()
        work_types = Counter()
        for worker_id in resolved_worker_ids:
            parameters = characters[worker_id]
            worker_sick = enum_name(parameters, "WorkerSick")
            physical_health = enum_name(parameters, "PhysicalHealth")
            if worker_sick or physical_health not in {"", "Healthful"}:
                sick_ids.add(worker_id)
            hunger = enum_name(parameters, "HungerType")
            if hunger not in {"", "Default"}:
                hungry_ids.add(worker_id)
            sanity = property_number(parameters, "SanityValue")
            if sanity is not None and sanity <= LOW_SANITY_THRESHOLD:
                low_sanity_ids.add(worker_id)
            work_type = enum_name(parameters, "CurrentWorkSuitability")
            if work_type:
                working_ids.add(worker_id)
                work_types[work_type] += 1

        problem_ids = sick_ids | hungry_ids | low_sanity_ids
        guild_pal_ids.setdefault(group_id, set()).update(resolved_worker_ids)
        guild_workers[group_id].update(resolved_worker_ids)
        guild_working[group_id].update(working_ids)
        guild_problems[group_id].update(problem_ids)
        bases.append(
            {
                "base_id": base_id,
                "group_id": group_id,
                "name": base_name(raw_data.get("name", ""), base_ordinals[group_id]),
                "location_x": translation.get("x", 0),
                "location_y": translation.get("y", 0),
                "location_z": translation.get("z", 0),
                "area_range": raw_data.get("area_range", 3500),
                "state": raw_data.get("state", -1),
                "player_count": player_counts.get(group_id, 0),
                "worker_count": len(resolved_worker_ids),
                "working_count": len(working_ids),
                "sick_count": len(sick_ids),
                "hungry_count": len(hungry_ids),
                "low_sanity_count": len(low_sanity_ids),
                "problem_worker_count": len(problem_ids),
                "work_types": [
                    {"key": work_type, "count": count}
                    for work_type, count in work_types.most_common(3)
                ],
                "raid_active": base_id in active_raid_base_ids,
            }
        )

    return bases, diagnostics, guild_workers, guild_working, guild_problems


def enrich_guilds(
    guilds,
    bases,
    guild_pal_ids,
    guild_workers,
    guild_working,
    guild_problems,
):
    base_counts = Counter(base["group_id"] for base in bases)
    active_raids = Counter(
        base["group_id"] for base in bases if base.get("raid_active")
    )
    for guild in guilds:
        group_id = guild["group_id"]
        guild.update(
            {
                "base_count": base_counts[group_id],
                "pal_count": len(guild_pal_ids.get(group_id, set())),
                "worker_count": len(guild_workers[group_id]),
                "working_count": len(guild_working[group_id]),
                "problem_worker_count": len(guild_problems[group_id]),
                "active_raid_count": active_raids[group_id],
            }
        )
    return guilds


def opaque_id(kind, value):
    source = f"{kind}:{to_str(value)}".encode("utf-8")
    return hashlib.sha256(source).hexdigest()[:20]


def minimize_payload(guilds, bases):
    guild_keys = {
        guild["group_id"]: opaque_id("guild", guild["group_id"])
        for guild in guilds
    }
    public_guilds = []
    for guild in guilds:
        public_guilds.append({
            key: value
            for key, value in guild.items()
            if key not in {
                "admin_player_uid",
                "base_ids",
                "players",
                "group_id",
                "group_name",
            }
        } | {
            "group_id": guild_keys[guild["group_id"]],
            "players": [
                {
                    "player_name": player["player_name"],
                    "is_admin": player["is_admin"],
                }
                for player in guild["players"]
            ],
        })

    public_bases = []
    for base in bases:
        public_bases.append({
            key: value
            for key, value in base.items()
            if key not in {
                "base_id",
                "group_id",
                "location_z",
                "area_range",
                "state",
                "player_count",
            }
        } | {
            "base_id": opaque_id("base", base["base_id"]),
            "group_id": guild_keys.get(
                base["group_id"], opaque_id("guild", base["group_id"])
            ),
        })
    return public_guilds, public_bases


def validate_world_data(world_data):
    if not isinstance(world_data, dict):
        raise ValueError("worldSaveData is missing or has an unsupported format")

    required_lists = (
        "GroupSaveDataMap",
        "BaseCampSaveData",
        "CharacterSaveParameterMap",
        "CharacterContainerSaveData",
    )
    datasets = {}
    for name in required_lists:
        dataset = world_data.get(name)
        if not isinstance(dataset, dict) or not isinstance(dataset.get("value"), list):
            raise ValueError(f"{name} is missing or has an unsupported format")
        datasets[name] = dataset["value"]

    group_entries = datasets["GroupSaveDataMap"]
    if not group_entries:
        raise ValueError("GroupSaveDataMap is empty")
    guild_count = 0
    for index, item in enumerate(group_entries):
        group_value = item.get("value", item) if isinstance(item, dict) else None
        if not isinstance(group_value, dict):
            raise ValueError(f"GroupSaveDataMap[{index}] is not decoded")
        group_type = property_value(group_value.get("GroupType"), "")
        if not group_type:
            raise ValueError(f"GroupSaveDataMap[{index}] has no group type")
        if group_type != "EPalGroupType::Guild":
            continue
        raw_property = group_value.get("RawData")
        raw_data = (
            raw_property.get("value") if isinstance(raw_property, dict) else None
        )
        required_fields = {
            "group_id",
            "group_name",
            "guild_name",
            "admin_player_uid",
            "players",
            "base_ids",
        }
        if (
            not isinstance(raw_data, dict)
            or not required_fields.issubset(raw_data)
            or not isinstance(raw_data["players"], list)
            or not isinstance(raw_data["base_ids"], list)
        ):
            raise ValueError(f"GroupSaveDataMap[{index}].RawData is not decoded")
        for player in raw_data["players"]:
            if (
                not isinstance(player, dict)
                or not to_str(player.get("player_uid"))
                or not isinstance(player.get("player_info"), dict)
            ):
                raise ValueError(f"GroupSaveDataMap[{index}] has an invalid player")
        guild_count += 1
    if not guild_count:
        raise ValueError("GroupSaveDataMap has no decoded guilds")

    character_entries = datasets["CharacterSaveParameterMap"]
    if not character_entries:
        raise ValueError("CharacterSaveParameterMap is empty")
    for index, item in enumerate(character_entries):
        if not isinstance(item, dict):
            raise ValueError(f"CharacterSaveParameterMap[{index}] is not decoded")
        item_value = item.get("value")
        raw_property = (
            item_value.get("RawData") if isinstance(item_value, dict) else None
        )
        raw_data = (
            raw_property.get("value") if isinstance(raw_property, dict) else None
        )
        raw_object = raw_data.get("object") if isinstance(raw_data, dict) else None
        save_parameter = (
            raw_object.get("SaveParameter") if isinstance(raw_object, dict) else None
        )
        save_parameters = (
            save_parameter.get("value")
            if isinstance(save_parameter, dict)
            else None
        )
        if not isinstance(save_parameters, dict):
            raise ValueError(
                f"CharacterSaveParameterMap[{index}].RawData is not decoded"
            )

    for index, item in enumerate(datasets["BaseCampSaveData"]):
        item_value = item.get("value") if isinstance(item, dict) else None
        raw_property = (
            item_value.get("RawData") if isinstance(item_value, dict) else None
        )
        raw_data = (
            raw_property.get("value") if isinstance(raw_property, dict) else None
        )
        transform = (
            raw_data.get("transform") if isinstance(raw_data, dict) else None
        )
        translation = (
            transform.get("translation") if isinstance(transform, dict) else None
        )
        required_fields = {
            "id",
            "name",
            "state",
            "transform",
            "group_id_belong_to",
        }
        if (
            not isinstance(raw_data, dict)
            or not required_fields.issubset(raw_data)
            or not isinstance(translation, dict)
        ):
            raise ValueError(f"BaseCampSaveData[{index}].RawData is not decoded")

    for index, item in enumerate(datasets["CharacterContainerSaveData"]):
        item_value = item.get("value") if isinstance(item, dict) else None
        slots_property = (
            item_value.get("Slots") if isinstance(item_value, dict) else None
        )
        slots_value = (
            slots_property.get("value")
            if isinstance(slots_property, dict)
            else None
        )
        slots = (
            slots_value.get("values")
            if isinstance(slots_value, dict)
            else None
        )
        if not isinstance(slots, list):
            raise ValueError(f"CharacterContainerSaveData[{index}] is not decoded")
        for slot in slots:
            raw_property = slot.get("RawData") if isinstance(slot, dict) else None
            if not isinstance(raw_property, dict) or "value" not in raw_property:
                raise ValueError(
                    f"CharacterContainerSaveData[{index}] has an invalid slot"
                )
            slot_data = raw_property["value"]
            if slot_data is not None and (
                not isinstance(slot_data, dict) or "instance_id" not in slot_data
            ):
                raise ValueError(
                    f"CharacterContainerSaveData[{index}].RawData is not decoded"
                )


def main():
    if not SITE_TOKEN:
        print("SITE_TOKEN is not set", file=sys.stderr)
        return 1

    from palsav.io import load_sav
    from palsav.paltypes import PALWORLD_CUSTOM_PROPERTIES

    datasets = (
        "GroupSaveDataMap",
        "BaseCampSaveData",
        "CharacterSaveParameterMap",
        "CharacterContainerSaveData",
    )
    custom_properties = {
        key: value
        for key, value in PALWORLD_CUSTOM_PROPERTIES.items()
        if any(dataset in key for dataset in datasets)
        and "BaseCampSaveData.Value.ModuleMap" not in key
        and "BaseCampSaveData.Value.WorkCollection" not in key
    }
    save = load_sav(SAVE_PATH, custom_properties=custom_properties)
    world_data = save.properties.get("worldSaveData", {}).get("value", {})
    try:
        validate_world_data(world_data)
    except ValueError as exc:
        print(f"Unable to parse save: {exc}", file=sys.stderr)
        return 1
    guilds = parse_guilds(world_data)
    characters, guild_pal_ids = index_characters(world_data, guilds)
    containers = index_character_containers(world_data)
    world, active_raid_base_ids = parse_world(world_data)
    (
        bases,
        diagnostics,
        guild_workers,
        guild_working,
        guild_problems,
    ) = parse_bases(
        world_data,
        guilds,
        characters,
        containers,
        guild_pal_ids,
        active_raid_base_ids,
    )
    enrich_guilds(
        guilds,
        bases,
        guild_pal_ids,
        guild_workers,
        guild_working,
        guild_problems,
    )
    public_guilds, public_bases = minimize_payload(guilds, bases)

    response = requests.post(
        f"{SITE_URL}/api/v1/guild/ingest",
        json={
            "schema_version": 2,
            "guilds": public_guilds,
            "bases": public_bases,
            "world": world,
            "diagnostics": diagnostics,
        },
        headers={"Authorization": f"Bearer {SITE_TOKEN}"},
        verify=VERIFY_SSL,
        timeout=15,
    )
    print(
        f"Sent {len(guilds)} guilds, {len(bases)} bases, "
        f"and {sum(guild['pal_count'] for guild in guilds)} Pals; "
        f"status={response.status_code}"
    )
    if not response.ok:
        print(response.text, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
