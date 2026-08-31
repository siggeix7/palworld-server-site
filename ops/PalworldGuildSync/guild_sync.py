#!/usr/bin/env python3
"""Send compact guild, base camp, world, and private claim data to the site."""

from collections import Counter, defaultdict
import hashlib
import os
import re
import stat
import sys
from urllib.parse import urlsplit

import requests


SAVE_PATH = os.getenv(
    "SAVE_PATH",
    "/opt/Palworld/palworld/Pal/Saved/SaveGames/0/"
    "36814278E2A240ADB8F57D42AAF739CD/Level.sav",
)
SITE_URL = os.getenv("SITE_URL", "").rstrip("/")
SITE_TOKEN = os.getenv("SITE_TOKEN", "")
VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() == "true"
ALLOW_INSECURE_HTTP = os.getenv("ALLOW_INSECURE_HTTP", "false").lower() == "true"
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
ZERO_GUID = ZERO_UUID.replace("-", "")
LOW_SANITY_THRESHOLD = 30
MAX_PLAYER_FILES = 4096
MAX_CLAIM_STACKS = 256
MAX_CLAIM_PARTY_PALS = 64
MAX_CLAIM_PROGRESS_KEYS = 8192
GUID_PATTERN = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
CUSTOM_PROPERTY_DATASETS = (
    "GroupSaveDataMap",
    "BaseCampSaveData",
    "CharacterSaveParameterMap",
    "CharacterContainerSaveData",
    "ItemContainerSaveData",
)
PLAYER_STATUS_NAMES = {
    "最大HP": "max_hp",
    "最大SP": "stamina",
    "攻撃力": "attack",
    "所持重量": "carry_weight",
    "捕獲率": "capture_rate",
    "作業速度": "work_speed",
}


class SaveChangedError(ValueError):
    pass


def to_str(value):
    if value is None:
        return ""
    return str(value)


def property_value(value, default=None):
    while isinstance(value, dict) and "value" in value:
        value = value["value"]
    return default if value is None else value


def normalized_identifier(value):
    text = to_str(property_value(value, "")).strip()
    compact = text.replace("-", "")
    return compact.casefold() if GUID_PATTERN.fullmatch(compact) else text.casefold()


def canonical_guid(value):
    identifier = normalized_identifier(value)
    return identifier if GUID_PATTERN.fullmatch(identifier) and identifier != ZERO_GUID else ""


def canonical_player_uid(value):
    return canonical_guid(value)


def dataset_values(world_data, name):
    value = property_value(world_data.get(name), [])
    return value if isinstance(value, list) else []


def claim_integer(value, maximum):
    value = property_value(value)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= maximum else None


def claim_text(value, maximum):
    value = property_value(value, "")
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > maximum or not all(character.isprintable() for character in value):
        return ""
    return value


def select_custom_properties(custom_properties):
    return {
        key: value
        for key, value in custom_properties.items()
        if any(dataset in key for dataset in CUSTOM_PROPERTY_DATASETS)
        and "BaseCampSaveData.Value.ModuleMap" not in key
        and "BaseCampSaveData.Value.WorkCollection" not in key
    }


def regular_file_signature(path):
    info = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("save artifact is not a regular file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def directory_signature(path):
    info = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("save directory is not a real directory")
    return info.st_dev, info.st_ino, info.st_mtime_ns


def property_number(properties, name):
    value = property_value(properties.get(name))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def nonnegative_int(value):
    value = property_value(value, 0)
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


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


def player_status_points(save_parameters):
    totals = Counter()
    for field in ("GotStatusPointList", "GotExStatusPointList"):
        payload = property_value(save_parameters.get(field), {})
        values = payload.get("values", []) if isinstance(payload, dict) else []
        for item in values:
            if not isinstance(item, dict):
                continue
            key = PLAYER_STATUS_NAMES.get(
                to_str(property_value(item.get("StatusName"), ""))
            )
            if key:
                totals[key] += nonnegative_int(item.get("StatusPoint"))
    return {
        key: totals[key]
        for key in PLAYER_STATUS_NAMES.values()
        if totals[key] > 0
    }


def parse_players(world_data, guilds):
    guild_members = {}
    for guild in guilds:
        for member in guild["players"]:
            player_uid = member["player_uid"]
            if not player_uid:
                continue
            candidate = {
                "player_uid": player_uid,
                "player_name": member["player_name"],
                "group_id": guild["group_id"],
                "is_admin": member["is_admin"],
            }
            current = guild_members.get(player_uid)
            if current is None or candidate["is_admin"]:
                guild_members[player_uid] = candidate

    players = {}
    pal_counts = Counter()
    for item in world_data.get("CharacterSaveParameterMap", {}).get("value", []):
        key = item.get("key", {})
        raw_data = item.get("value", {}).get("RawData", {}).get("value", {})
        save_parameters = (
            raw_data.get("object", {}).get("SaveParameter", {}).get("value", {})
        )
        if not property_value(save_parameters.get("IsPlayer"), False):
            owner_id = to_str(
                property_value(save_parameters.get("OwnerPlayerUId"), "")
            )
            if owner_id:
                pal_counts[owner_id] += 1
            continue

        player_uid = to_str(property_value(key.get("PlayerUId"), ""))
        if not player_uid or player_uid == ZERO_UUID:
            continue
        member = guild_members.get(player_uid, {})
        player_name = (
            to_str(property_value(save_parameters.get("NickName"), "")).strip()
            or to_str(
                property_value(save_parameters.get("FilteredNickName"), "")
            ).strip()
            or to_str(member.get("player_name", "")).strip()
        )
        if not player_name:
            continue
        players[player_uid] = {
            "player_uid": player_uid,
            "player_name": player_name[:128],
            "group_id": to_str(member.get("group_id", "")),
            "is_admin": bool(member.get("is_admin", False)),
            "level": nonnegative_int(save_parameters.get("Level")),
            "exp": nonnegative_int(save_parameters.get("Exp")),
            "unused_status_points": nonnegative_int(
                save_parameters.get("UnusedStatusPoint")
            ),
            "status_points": player_status_points(save_parameters),
            "owned_pal_count": 0,
        }

    for player_uid, member in guild_members.items():
        if player_uid in players or not member["player_name"]:
            continue
        players[player_uid] = {
            **member,
            "level": 0,
            "exp": 0,
            "unused_status_points": 0,
            "status_points": {},
            "owned_pal_count": 0,
        }

    for player_uid, player in players.items():
        player["owned_pal_count"] = pal_counts[player_uid]
    return sorted(players.values(), key=lambda player: player["player_name"].casefold())


def true_flag_keys(record_data, name):
    if name not in record_data:
        return []
    entries = property_value(record_data.get(name))
    if not isinstance(entries, list):
        raise ValueError(f"{name} is not a map")

    keys = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{name} contains an invalid entry")
        key = claim_text(entry.get("key"), 256)
        if not key:
            raise ValueError(f"{name} contains an empty key")
        key = key.casefold()
        if key in seen:
            raise ValueError(f"{name} repeats a key")
        seen.add(key)
        flag = property_value(entry.get("value"))
        if not isinstance(flag, bool):
            raise ValueError(f"{name} contains a non-boolean value")
        if flag:
            keys.append(key)
    if len(keys) > MAX_CLAIM_PROGRESS_KEYS:
        raise ValueError(f"{name} contains too many entries")
    return sorted(keys)


def parse_claim_progress(save_data):
    record_data = property_value(save_data.get("RecordData"), {})
    if record_data is None:
        record_data = {}
    if not isinstance(record_data, dict):
        raise ValueError("RecordData is not an object")
    return {
        "fast_travel": true_flag_keys(
            record_data, "FastTravelPointUnlockFlag"
        ),
        "areas": true_flag_keys(record_data, "FindAreaFlagMap"),
        "notes": true_flag_keys(record_data, "NoteObtainForInstanceFlag"),
        "relics": true_flag_keys(record_data, "RelicObtainForInstanceFlag"),
        "item_pickups": true_flag_keys(
            record_data, "ItemPickupObtainForInstanceFlag"
        ),
        "normal_bosses": true_flag_keys(
            record_data, "NormalBossDefeatFlag"
        ),
        "tower_bosses": true_flag_keys(record_data, "TowerBossDefeatFlag"),
    }


def container_id(value):
    value = property_value(value)
    if not isinstance(value, dict):
        return canonical_guid(value)
    return canonical_guid(value.get("ID"))


def index_claim_item_containers(world_data):
    containers = {}
    for item in dataset_values(world_data, "ItemContainerSaveData"):
        if not isinstance(item, dict):
            continue
        key = item.get("key", {})
        key_value = key.get("ID") if isinstance(key, dict) else key
        identifier = canonical_guid(key_value)
        value = property_value(item.get("value"), {})
        if identifier and isinstance(value, dict):
            if identifier in containers:
                raise ValueError("ItemContainerSaveData repeats a container")
            containers[identifier] = value
    return containers


def index_claim_character_containers(world_data):
    containers = {}
    for item in dataset_values(world_data, "CharacterContainerSaveData"):
        if not isinstance(item, dict):
            continue
        key = item.get("key", {})
        key_value = key.get("ID") if isinstance(key, dict) else key
        identifier = canonical_guid(key_value)
        value = property_value(item.get("value"), {})
        if identifier and isinstance(value, dict):
            if identifier in containers:
                raise ValueError("CharacterContainerSaveData repeats a container")
            containers[identifier] = value
    return containers


def index_claim_characters(world_data):
    characters = {}
    for item in dataset_values(world_data, "CharacterSaveParameterMap"):
        if not isinstance(item, dict):
            continue
        key = item.get("key", {})
        instance_value = key.get("InstanceId") if isinstance(key, dict) else ""
        instance_id = canonical_guid(instance_value)
        value = property_value(item.get("value"), {})
        raw_data = property_value(value.get("RawData"), {}) if isinstance(value, dict) else {}
        raw_object = raw_data.get("object") if isinstance(raw_data, dict) else {}
        save_parameters = (
            property_value(raw_object.get("SaveParameter"), {})
            if isinstance(raw_object, dict)
            else {}
        )
        if instance_id and isinstance(save_parameters, dict):
            species = claim_text(save_parameters.get("CharacterID"), 256)
            if species:
                if instance_id in characters:
                    raise ValueError("CharacterSaveParameterMap repeats a character")
                characters[instance_id] = species
    return characters


def claim_slot_data(slot):
    if not isinstance(slot, dict):
        return None
    value = property_value(slot.get("RawData"))
    return value if isinstance(value, dict) else None


def parse_claim_inventory(container):
    slots_value = property_value(container.get("Slots"), {})
    slots = slots_value.get("values") if isinstance(slots_value, dict) else None
    if not isinstance(slots, list):
        return []

    stacks = []
    seen_slots = set()
    for slot in slots:
        data = claim_slot_data(slot)
        if data is None:
            continue
        slot_index = claim_integer(data.get("slot_index"), 1023)
        count = claim_integer(data.get("count"), 2**32 - 1)
        item = data.get("item")
        item_id = claim_text(item.get("static_id"), 256) if isinstance(item, dict) else ""
        if slot_index is None or count is None or count == 0 or not item_id:
            continue
        if slot_index in seen_slots:
            raise ValueError("inventory repeats a slot")
        seen_slots.add(slot_index)
        stack = {"slot": slot_index, "item_id": item_id, "count": count}
        dynamic = item.get("dynamic_id") if isinstance(item, dict) else None
        if isinstance(dynamic, dict):
            identifier = canonical_guid(dynamic.get("local_id_in_created_world"))
            if identifier:
                stack["dynamic_item_id"] = identifier
        stacks.append(stack)

    if len(stacks) > MAX_CLAIM_STACKS:
        raise ValueError("inventory contains too many stacks")
    return sorted(stacks, key=lambda stack: stack["slot"])


def parse_claim_party(container, characters):
    slots_value = property_value(container.get("Slots"), {})
    slots = slots_value.get("values") if isinstance(slots_value, dict) else None
    if not isinstance(slots, list):
        return []

    party = []
    seen_slots = set()
    seen_instances = set()
    for slot in slots:
        data = claim_slot_data(slot)
        if data is None:
            continue
        instance_id = canonical_guid(data.get("instance_id"))
        species = characters.get(instance_id, "")
        slot_index = claim_integer(slot.get("SlotIndex"), 63)
        if not instance_id or instance_id == ZERO_GUID or not species or slot_index is None:
            continue
        if slot_index in seen_slots or instance_id in seen_instances:
            raise ValueError("party repeats a slot or Pal")
        seen_slots.add(slot_index)
        seen_instances.add(instance_id)
        party.append({
            "slot": slot_index,
            "species": species,
            "instance_id": instance_id,
        })

    if len(party) > MAX_CLAIM_PARTY_PALS:
        raise ValueError("party contains too many Pals")
    return sorted(party, key=lambda pal: pal["slot"])


def parse_claim_player(
    properties,
    player_name,
    item_containers,
    character_containers,
    characters,
):
    save_data = property_value(properties.get("SaveData"), {})
    if not isinstance(save_data, dict):
        raise ValueError("SaveData is missing or has an unsupported format")
    player_uid = canonical_player_uid(save_data.get("PlayerUId"))
    if not player_uid:
        raise ValueError("player save has no valid PlayerUId")
    player_name = claim_text(player_name, 128)
    if not player_name:
        raise ValueError("player save has no matching player name")

    inventory_info = property_value(save_data.get("InventoryInfo"), {})
    if not isinstance(inventory_info, dict):
        raise ValueError("player save has no InventoryInfo")
    inventory = {}
    for output_name, source_name in (
        ("common", "CommonContainerId"),
        ("weapons", "WeaponLoadOutContainerId"),
        ("armor", "PlayerEquipArmorContainerId"),
        ("food", "FoodEquipContainerId"),
        ("drop_slot", "DropSlotContainerId"),
        ("essential", "EssentialContainerId"),
    ):
        identifier = container_id(inventory_info.get(source_name))
        container = item_containers.get(identifier)
        inventory[output_name] = parse_claim_inventory(container) if container else []

    party_identifier = container_id(save_data.get("OtomoCharacterContainerId"))
    party_container = character_containers.get(party_identifier)
    return {
        "player_uid": player_uid,
        "player_name": player_name,
        "inventory": inventory,
        "party": parse_claim_party(party_container, characters)
        if party_container
        else [],
        "progress": parse_claim_progress(save_data),
    }


def save_properties(save):
    properties = getattr(save, "properties", save)
    if isinstance(properties, dict) and isinstance(properties.get("properties"), dict):
        properties = properties["properties"]
    if not isinstance(properties, dict):
        raise ValueError("player save has an unsupported format")
    return properties


def parse_claim_players(
    save_path,
    world_data,
    players,
    load_player_save,
    expected_level_signature=None,
):
    player_names = {}
    duplicate_names = set()
    for player in players:
        player_uid = canonical_player_uid(player.get("player_uid"))
        player_name = claim_text(player.get("player_name"), 128)
        if not player_uid or not player_name:
            continue
        if player_uid in player_names and player_names[player_uid] != player_name:
            duplicate_names.add(player_uid)
        else:
            player_names[player_uid] = player_name
    for player_uid in duplicate_names:
        player_names.pop(player_uid, None)

    level_signature = regular_file_signature(save_path)
    if expected_level_signature is not None and level_signature != expected_level_signature:
        raise SaveChangedError("Level.sav changed before player parsing")
    players_directory = os.path.join(os.path.dirname(os.path.abspath(save_path)), "Players")
    try:
        players_directory_signature = directory_signature(players_directory)
    except FileNotFoundError:
        if player_names:
            raise ValueError("Players directory is missing")
        return []

    player_files = []
    with os.scandir(players_directory) as entries:
        for entry in entries:
            lower_name = entry.name.casefold()
            entry_info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(entry_info.st_mode):
                if lower_name.endswith(".sav") and not lower_name.endswith("_dps.sav"):
                    raise ValueError("player save is a symlink")
                continue
            if (
                stat.S_ISREG(entry_info.st_mode)
                and lower_name.endswith(".sav")
                and not lower_name.endswith("_dps.sav")
            ):
                player_files.append(entry.path)
    if len(player_files) > MAX_PLAYER_FILES:
        raise ValueError("Players directory contains too many save files")

    item_containers = index_claim_item_containers(world_data)
    character_containers = index_claim_character_containers(world_data)
    characters = index_claim_characters(world_data)
    claims = {}
    for player_file in sorted(player_files, key=lambda path: os.path.basename(path).casefold()):
        try:
            player_signature = regular_file_signature(player_file)
            properties = save_properties(load_player_save(player_file))
            if regular_file_signature(player_file) != player_signature:
                raise SaveChangedError("player save changed during parsing")
            save_data = property_value(properties.get("SaveData"), {})
            player_uid = (
                canonical_player_uid(save_data.get("PlayerUId"))
                if isinstance(save_data, dict)
                else ""
            )
            claim = parse_claim_player(
                properties,
                player_names.get(player_uid, ""),
                item_containers,
                character_containers,
                characters,
            )
        except SaveChangedError:
            raise
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        player_uid = claim["player_uid"]
        if player_uid not in player_names:
            continue
        claim["player_name"] = player_names[player_uid]
        if player_uid in claims:
            raise ValueError("Players directory contains duplicate player identities")
        claims[player_uid] = claim

    if regular_file_signature(save_path) != level_signature:
        raise SaveChangedError("Level.sav changed during player parsing")
    if directory_signature(players_directory) != players_directory_signature:
        raise SaveChangedError("Players directory changed during parsing")
    if player_names and not claims:
        raise ValueError("Unable to parse any player saves")
    return sorted(claims.values(), key=lambda claim: claim["player_uid"])


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


def minimize_payload(guilds, bases, players):
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
    public_players = [
        {
            "player_id": opaque_id("player", player["player_uid"]),
            "player_name": player["player_name"],
            "guild_id": guild_keys.get(player["group_id"], ""),
            "is_admin": player["is_admin"],
            "level": player["level"],
            "exp": player["exp"],
            "owned_pal_count": player["owned_pal_count"],
            "unused_status_points": player["unused_status_points"],
            "status_points": player["status_points"],
        }
        for player in players
    ]
    return public_guilds, public_bases, public_players


def validate_world_data(world_data):
    if not isinstance(world_data, dict):
        raise ValueError("worldSaveData is missing or has an unsupported format")

    required_lists = (
        "GroupSaveDataMap",
        "BaseCampSaveData",
        "CharacterSaveParameterMap",
        "CharacterContainerSaveData",
        "ItemContainerSaveData",
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

    for index, item in enumerate(datasets["ItemContainerSaveData"]):
        item_value = item.get("value") if isinstance(item, dict) else None
        slots_property = (
            item_value.get("Slots") if isinstance(item_value, dict) else None
        )
        slots_value = property_value(slots_property, {})
        slots = slots_value.get("values") if isinstance(slots_value, dict) else None
        if not isinstance(slots, list):
            raise ValueError(f"ItemContainerSaveData[{index}] is not decoded")
        for slot in slots:
            raw_property = slot.get("RawData") if isinstance(slot, dict) else None
            if not isinstance(raw_property, dict) or "value" not in raw_property:
                raise ValueError(
                    f"ItemContainerSaveData[{index}] has an invalid slot"
                )
            slot_data = property_value(raw_property)
            if slot_data is not None and (
                not isinstance(slot_data, dict)
                or not {"slot_index", "count", "item"}.issubset(slot_data)
            ):
                raise ValueError(
                    f"ItemContainerSaveData[{index}].RawData is not decoded"
                )


def main():
    site = urlsplit(SITE_URL)
    if site.scheme not in {"http", "https"} or not site.hostname:
        print("SITE_URL must be an absolute HTTP(S) origin", file=sys.stderr)
        return 1
    if site.scheme == "http" and not ALLOW_INSECURE_HTTP:
        print("HTTP SITE_URL requires ALLOW_INSECURE_HTTP=true", file=sys.stderr)
        return 1
    if not SITE_TOKEN:
        print("SITE_TOKEN is not set", file=sys.stderr)
        return 1

    from palsav.io import load_sav
    from palsav.paltypes import PALWORLD_CUSTOM_PROPERTIES

    custom_properties = select_custom_properties(PALWORLD_CUSTOM_PROPERTIES)
    try:
        level_signature = regular_file_signature(SAVE_PATH)
        save = load_sav(SAVE_PATH, custom_properties=custom_properties)
        if regular_file_signature(SAVE_PATH) != level_signature:
            raise SaveChangedError("Level.sav changed during parsing")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        print(f"Unable to parse save: {exc}", file=sys.stderr)
        return 1
    world_data = save.properties.get("worldSaveData", {}).get("value", {})
    try:
        validate_world_data(world_data)
    except ValueError as exc:
        print(f"Unable to parse save: {exc}", file=sys.stderr)
        return 1
    guilds = parse_guilds(world_data)
    players = parse_players(world_data, guilds)
    try:
        claim_players = parse_claim_players(
            SAVE_PATH,
            world_data,
            players,
            lambda path: load_sav(path, custom_properties=custom_properties),
            expected_level_signature=level_signature,
        )
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        print(f"Unable to parse player saves: {exc}", file=sys.stderr)
        return 1
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
    public_guilds, public_bases, public_players = minimize_payload(
        guilds, bases, players
    )

    with requests.Session() as session:
        session.trust_env = False
        response = session.post(
            f"{SITE_URL}/api/v1/guild/ingest",
            json={
                "schema_version": 4,
                "guilds": public_guilds,
                "bases": public_bases,
                "players": public_players,
                "world": world,
                "diagnostics": diagnostics,
                "claim": {"players": claim_players},
            },
            headers={"Authorization": f"Bearer {SITE_TOKEN}"},
            verify=VERIFY_SSL,
            timeout=15,
        )
    print(
        f"Sent {len(guilds)} guilds, {len(bases)} bases, {len(players)} players, "
        f"and {sum(guild['pal_count'] for guild in guilds)} Pals; "
        f"status={response.status_code}"
    )
    if not response.ok:
        print(response.text, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
