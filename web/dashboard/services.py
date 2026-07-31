import hashlib
import hmac
import json
import math
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import (
    LatestDataset,
    MetricSample,
    Player,
    PlayerSession,
    PositionSample,
    RuntimeState,
    ServerEvent,
)

DATASETS = {
    "game_data",
    "info",
    "metrics",
    "players",
    "settings",
    "status",
}

SAFE_SETTING_KEYS = {
    "Difficulty",
    "DayTimeSpeedRate",
    "NightTimeSpeedRate",
    "ExpRate",
    "PalCaptureRate",
    "PalSpawnNumRate",
    "PalDamageRateAttack",
    "PalDamageRateDefense",
    "PlayerDamageRateAttack",
    "PlayerDamageRateDefense",
    "PlayerStomachDecreaceRate",
    "PlayerStaminaDecreaceRate",
    "PlayerAutoHPRegeneRate",
    "PlayerAutoHpRegeneRateInSleep",
    "PalStomachDecreaceRate",
    "PalStaminaDecreaceRate",
    "PalAutoHPRegeneRate",
    "PalAutoHpRegeneRateInSleep",
    "BuildObjectDamageRate",
    "BuildObjectDeteriorationDamageRate",
    "CollectionDropRate",
    "CollectionObjectHpRate",
    "CollectionObjectRespawnSpeedRate",
    "EnemyDropItemRate",
    "DeathPenalty",
    "bEnablePlayerToPlayerDamage",
    "bEnableFriendlyFire",
    "bEnableInvaderEnemy",
    "DropItemMaxNum",
    "BaseCampMaxNum",
    "BaseCampWorkerMaxNum",
    "DropItemAliveMaxHours",
    "bAutoResetGuildNoOnlinePlayers",
    "AutoResetGuildTimeNoOnlinePlayers",
    "GuildPlayerMaxNum",
    "PalEggDefaultHatchingTime",
    "WorkSpeedRate",
    "bIsPvP",
    "bCanPickupOtherGuildDeathPenaltyDrop",
    "bEnableNonLoginPenalty",
    "bEnableFastTravel",
    "bIsStartLocationSelectByMap",
    "bExistPlayerAfterLogout",
    "bEnableDefenseOtherGuildPlayer",
    "CoopPlayerMaxNum",
    "ServerPlayerMaxNum",
    "ServerName",
    "ServerDescription",
    "AllowConnectPlatform",
    "CrossplayPlatforms",
    "bIsUseBackupSaveData",
}


class IngestError(ValueError):
    pass


def _clean_text(value, limit=128):
    text = "" if value is None else str(value)
    text = "".join(char for char in text if char.isprintable()).strip()
    return text[:limit]


def _number(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _integer(value, default=0):
    try:
        number = float(value)
        if not math.isfinite(number):
            return default
        return max(0, int(number))
    except (TypeError, ValueError, OverflowError):
        return default


def _first_present(mapping, *keys):
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _payload(value):
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise IngestError(f"dataset value is not valid JSON: {exc.msg}") from exc
    raise IngestError("dataset value must be a JSON object or string")


def _player_id(raw):
    identity = (
        raw.get("userId")
        or raw.get("user_id")
        or raw.get("playerId")
        or raw.get("player_uid")
        or raw.get("playerUid")
        or raw.get("accountName")
        or raw.get("account_name")
        or raw.get("name")
        or raw.get("nickname")
        or "unknown"
    )
    return hmac.new(
        settings.PLAYER_HASH_SECRET.encode("utf-8"),
        str(identity).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]


def _sanitize_info(value):
    value = _payload(value)
    if not isinstance(value, dict):
        raise IngestError("info dataset must be an object")
    return {
        "version": _clean_text(value.get("version"), 64),
        "servername": _clean_text(value.get("servername"), 128),
        "description": _clean_text(value.get("description"), 512),
    }


def _sanitize_metrics(value):
    value = _payload(value)
    if not isinstance(value, dict):
        raise IngestError("metrics dataset must be an object")
    required = {
        "currentplayernum",
        "maxplayernum",
        "serverfps",
        "serverframetime",
        "days",
        "uptime",
    }
    if not required.issubset(value):
        raise IngestError("metrics dataset is missing required fields")
    return {
        "currentplayernum": _integer(value.get("currentplayernum")),
        "maxplayernum": _integer(value.get("maxplayernum")),
        "serverfps": _number(value.get("serverfps")),
        "serverfpsaverage": _number(value.get("serverfpsaverage", value.get("serverfps"))),
        "serverframetime": _number(value.get("serverframetime")),
        "days": _integer(value.get("days")),
        "basecampnum": _integer(value.get("basecampnum")),
        "uptime": _integer(value.get("uptime")),
    }


def _sanitize_settings(value):
    value = _payload(value)
    if not isinstance(value, dict):
        raise IngestError("settings dataset must be an object")
    return {key: value[key] for key in sorted(SAFE_SETTING_KEYS) if key in value}


def _sanitize_players(value):
    value = _payload(value)
    if (
        not isinstance(value, dict)
        or "players" not in value
        or not isinstance(value["players"], list)
    ):
        raise IngestError("players dataset must contain a players array")

    raw_players = [raw for raw in value.get("players", []) if isinstance(raw, dict)]
    user_counts = {}
    player_counts = {}
    for raw in raw_players:
        user_id = _canonical_external_id(
            _first_present(raw, "userId", "user_id")
        )
        player_id = _canonical_external_id(
            _first_present(raw, "playerId", "player_uid", "playerUid")
        )
        if user_id:
            user_counts[user_id] = user_counts.get(user_id, 0) + 1
        if player_id:
            player_counts[player_id] = player_counts.get(player_id, 0) + 1

    # Field aliases follow RNZ01's payload normalizer; raw IDs remain HMAC inputs only.
    # Adapted from lib/palworld.ts at upstream commit 588fa639; see NOTICE.md.
    players = []
    for raw in raw_players:
        name = _clean_text(raw.get("name") or raw.get("nickname"), 128)
        if not name:
            continue
        raw_user_id = _first_present(raw, "userId", "user_id")
        raw_player_id = _first_present(raw, "playerId", "player_uid", "playerUid")
        user_id = _canonical_external_id(raw_user_id)
        player_id = _canonical_external_id(raw_player_id)
        if user_id and user_counts.get(user_id) == 1:
            public_id = _player_id(raw)
        elif player_id and player_counts.get(player_id) == 1:
            public_id = _player_id({"playerId": raw_player_id})
        elif user_id or player_id:
            continue
        else:
            public_id = _player_id(raw)
        players.append(
            {
                "id": public_id,
                "name": name,
                "accountName": _clean_text(
                    raw.get("accountName") or raw.get("account_name"), 128
                ),
                "ping": round(_number(raw.get("ping")), 2),
                "location_x": _number(_first_present(raw, "location_x", "locationX")),
                "location_y": _number(_first_present(raw, "location_y", "locationY")),
                "level": _integer(raw.get("level")),
                "building_count": _integer(_first_present(raw, "building_count", "buildingCount")),
            }
        )
    players.sort(key=lambda player: player["name"].casefold())
    return {"players": players}


def _sanitize_status(value):
    if isinstance(value, str):
        value = value.strip().lower()
    return {"reachable": value in (1, 1.0, True, "1", "true", "up")}


# Shared by the live-map adapters so live objects use the same Palpagos and
# World Tree projections as the pinned upstream map assets. World Tree is
# checked first because its bounds overlap a narrow edge of Palpagos.
WORLD_MAP_BOUNDS = {
    "world-tree": {
        "min_x": 347351.5,
        "max_x": 689148.5,
        "min_y": -818197,
        "max_y": -476400,
    },
    "palpagos": {
        "min_x": -1099400,
        "max_x": 349400,
        "min_y": -724400,
        "max_y": 724400,
    },
}

MAX_WORLD_OBJECTS = 20000
BASE_ASSOCIATION_RADIUS_SQ = (3500 * 1.025) ** 2

WORLD_ACTOR_KINDS = (
    "bases",
    "players",
    "workers",
    "companions",
    "npcs",
    "wild-pals",
)
INCLUDED_WORLD_KINDS = set(WORLD_ACTOR_KINDS) - {"players"}
WORLD_OBJECT_PRIORITY = {
    "bases": 0,
    "workers": 1,
    "companions": 2,
    "npcs": 3,
    "wild-pals": 4,
}

_ACTOR_KIND_MAP = {
    "palbox": "bases",
    "player": "players",
    "basecamppal": "workers",
    "wildpal": "wild-pals",
    "otomopal": "companions",
    "npc": "npcs",
}


def _world_object_id(instance_id, kind):
    return hmac.new(
        settings.PLAYER_HASH_SECRET.encode("utf-8"),
        f"world:{kind}:{instance_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]


def _world_relation_id(namespace, identity):
    return hmac.new(
        settings.PLAYER_HASH_SECRET.encode("utf-8"),
        f"world:{namespace}:{identity}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]


def _humanize_class(class_name):
    text = "" if class_name is None else str(class_name)
    if text.startswith("BP_"):
        text = text[3:]
    if text.endswith("_C"):
        text = text[:-2]
    return text.replace("_", " ").strip()


def _classify_world_actor(actor):
    actor_type = actor.get("Type")
    if isinstance(actor_type, str) and actor_type.strip().casefold() == "palbox":
        return "bases"
    unit_type = actor.get("UnitType")
    if not isinstance(unit_type, str):
        return None
    return _ACTOR_KIND_MAP.get(unit_type.strip().casefold())


def _is_active_value(value):
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in ("", "true")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    return False


def _world_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _canonical_external_id(value):
    return value.strip().casefold() if isinstance(value, str) else ""


def _player_id_from_instance(value):
    value = _canonical_external_id(value)
    parts = [part.strip() for part in value.split(":")]
    if len(parts) == 1 and len(parts[0]) == 32:
        player_id = parts[0]
    elif (
        len(parts) == 2
        and all(len(part) == 32 for part in parts)
        and all(all(char in "0123456789abcdef" for char in part) for part in parts)
    ):
        player_id = parts[0]
    else:
        return ""
    return player_id if all(char in "0123456789abcdef" for char in player_id) else ""


def _world_identity(actor, kind, guild_id, x, y):
    instance_id = _canonical_external_id(actor.get("InstanceID"))
    if instance_id:
        return instance_id
    if kind == "bases":
        return "\0".join((
            "palbox",
            guild_id,
            str(actor.get("Class") or "").strip(),
            format(x, ".15g"),
            format(y, ".15g"),
        ))
    owner_id = _canonical_external_id(actor.get("TrainerInstanceID"))
    if not owner_id:
        owner_id = _canonical_external_id(actor.get("userid"))
    if not owner_id:
        return ""
    return "\0".join((
        "owned",
        kind,
        owner_id,
        guild_id,
        str(actor.get("Class") or "").strip(),
        _clean_text(actor.get("NickName"), 96),
    ))


def _map_for_coords(x, y):
    for map_id, bounds in WORLD_MAP_BOUNDS.items():
        if (
            bounds["min_x"] <= x <= bounds["max_x"]
            and bounds["min_y"] <= y <= bounds["max_y"]
        ):
            return map_id
    return None


def _sanitize_game_data(value):
    value = _payload(value)
    if not isinstance(value, dict):
        raise IngestError("game_data dataset must be an object")
    actor_data = value.get("ActorData")
    if not isinstance(actor_data, list):
        raise IngestError("game_data dataset must contain an ActorData array")

    source_counts = {kind: 0 for kind in WORLD_ACTOR_KINDS}
    active_counts = {kind: 0 for kind in WORLD_ACTOR_KINDS}
    omitted_counts = {
        "unsupported": 0,
        "inactive": 0,
        "invalid_coordinates": 0,
        "outside_maps": 0,
        "missing_identity": 0,
        "ambiguous_identity": 0,
    }

    # First pass: build canonical InstanceID -> public player ID joins. Raw IDs
    # never leave this function and are not included in diagnostics.
    player_instance_counts = {}
    player_user_counts = {}
    player_id_counts = {}
    for actor in actor_data:
        if not isinstance(actor, dict):
            continue
        if (
            _classify_world_actor(actor) != "players"
            or not _is_active_value(actor.get("IsActive"))
        ):
            continue
        instance_id = _canonical_external_id(actor.get("InstanceID"))
        if instance_id:
            player_instance_counts[instance_id] = player_instance_counts.get(instance_id, 0) + 1
        user_id = _canonical_external_id(actor.get("userid"))
        if user_id:
            player_user_counts[user_id] = player_user_counts.get(user_id, 0) + 1
        player_id = _player_id_from_instance(actor.get("InstanceID"))
        if player_id:
            player_id_counts[player_id] = player_id_counts.get(player_id, 0) + 1

    player_id_map = {}
    for actor in actor_data:
        if not isinstance(actor, dict):
            continue
        if (
            _classify_world_actor(actor) != "players"
            or not _is_active_value(actor.get("IsActive"))
        ):
            continue
        instance_id = _canonical_external_id(actor.get("InstanceID"))
        if not instance_id or player_instance_counts.get(instance_id) != 1:
            continue
        userid = actor.get("userid")
        canonical_user_id = _canonical_external_id(userid)
        player_id = _player_id_from_instance(actor.get("InstanceID"))
        public_ids = []
        if canonical_user_id and player_user_counts.get(canonical_user_id) == 1:
            public_ids.extend((
                _player_id({"userId": userid}),
                _player_id({"userId": canonical_user_id}),
            ))
        if player_id and player_id_counts.get(player_id) == 1:
            raw_player_id = str(actor.get("InstanceID")).strip().split(":", 1)[0].strip()
            public_ids.extend((
                _player_id({"playerId": raw_player_id}),
                _player_id({"playerId": player_id}),
            ))
        if not public_ids:
            continue
        player_id_map[instance_id] = list(dict.fromkeys(public_ids))

    candidates = []
    identity_counts = {}
    for actor in actor_data:
        if not isinstance(actor, dict):
            omitted_counts["unsupported"] += 1
            continue
        kind = _classify_world_actor(actor)
        if kind not in WORLD_ACTOR_KINDS:
            omitted_counts["unsupported"] += 1
            continue
        source_counts[kind] += 1
        if not _is_active_value(actor.get("IsActive")):
            omitted_counts["inactive"] += 1
            continue
        active_counts[kind] += 1
        if kind == "players":
            continue
        x = _world_number(actor.get("LocationX"))
        y = _world_number(actor.get("LocationY"))
        if x is None or y is None:
            omitted_counts["invalid_coordinates"] += 1
            continue
        map_id = _map_for_coords(x, y)
        if map_id is None:
            omitted_counts["outside_maps"] += 1
            continue
        guild_id = _canonical_external_id(actor.get("GuildID"))
        identity = _world_identity(actor, kind, guild_id, x, y)
        if not identity:
            omitted_counts["missing_identity"] += 1
            continue

        nick_name = _clean_text(actor.get("NickName"), 96)
        class_name = _clean_text(_humanize_class(actor.get("Class")), 96)
        if kind == "bases":
            name = _clean_text(actor.get("GuildName"), 96) or "Palbox"
            class_name = ""
        else:
            name = nick_name or class_name or {
                "workers": "Base worker",
                "wild-pals": "Wild Pal",
                "companions": "Companion Pal",
                "npcs": "NPC",
            }.get(kind, "Map object")
        obj = {
            "id": _world_object_id(identity, kind),
            "kind": kind,
            "name": name,
            "x": round(x, 2),
            "y": round(y, 2),
            "map": map_id,
        }
        if class_name and class_name != name:
            obj["detail"] = class_name
        level = _integer(_first_present(actor, "level", "Level"))
        if level > 0:
            obj["level"] = level
        if kind == "companions":
            owner_ids = player_id_map.get(
                _canonical_external_id(actor.get("TrainerInstanceID"))
            )
            if owner_ids:
                obj["owner_id"] = owner_ids[0]
                if len(owner_ids) > 1:
                    obj["owner_ids"] = owner_ids
        guild_name = _clean_text(actor.get("GuildName"), 128)
        if guild_name:
            obj["guild_name"] = guild_name
        if guild_id and kind in {"bases", "workers", "companions"}:
            obj["guild_key"] = _world_relation_id("guild", guild_id)
        candidate = {
            "identity": identity,
            "guild_id": guild_id,
            "x": x,
            "y": y,
            "object": obj,
        }
        candidates.append(candidate)
        identity_counts[identity] = identity_counts.get(identity, 0) + 1

    unique_candidates = []
    for candidate in candidates:
        if identity_counts[candidate["identity"]] != 1:
            omitted_counts["ambiguous_identity"] += 1
            continue
        unique_candidates.append(candidate)
    unique_candidates.sort(key=lambda candidate: (
        WORLD_OBJECT_PRIORITY[candidate["object"]["kind"]],
        candidate["identity"],
    ))
    supported_count = len(unique_candidates)
    retained = unique_candidates[:MAX_WORLD_OBJECTS]

    bases_by_guild_map = {}
    for candidate in retained:
        obj = candidate["object"]
        if obj["kind"] != "bases":
            continue
        obj["base_id"] = obj["id"]
        key = (candidate["guild_id"], obj["map"])
        bases_by_guild_map.setdefault(key, []).append(candidate)
    for candidate in retained:
        obj = candidate["object"]
        guild_id = candidate["guild_id"]
        if obj["kind"] != "workers" or not guild_id:
            continue
        nearest = None
        nearest_distance_sq = math.inf
        for base in bases_by_guild_map.get((guild_id, obj["map"]), []):
            distance_sq = (
                (candidate["x"] - base["x"]) ** 2
                + (candidate["y"] - base["y"]) ** 2
            )
            if distance_sq > BASE_ASSOCIATION_RADIUS_SQ:
                continue
            if (
                nearest is None
                or distance_sq < nearest_distance_sq
                or (
                    distance_sq == nearest_distance_sq
                    and base["identity"] < nearest["identity"]
                )
            ):
                nearest = base
                nearest_distance_sq = distance_sq
        if nearest is not None:
            obj["base_id"] = nearest["object"]["base_id"]

    objects = [candidate["object"] for candidate in retained]
    kind_counts = {
        kind: 0 for kind in WORLD_ACTOR_KINDS if kind in INCLUDED_WORLD_KINDS
    }
    for obj in objects:
        kind_counts[obj["kind"]] += 1
    return {
        "objects": objects,
        "count": len(objects),
        "source_count": len(actor_data),
        "supported_count": supported_count,
        "source_counts": source_counts,
        "active_counts": active_counts,
        "kind_counts": kind_counts,
        "omitted_counts": omitted_counts,
        "truncated": supported_count > MAX_WORLD_OBJECTS,
    }


SANITIZERS = {
    "info": _sanitize_info,
    "metrics": _sanitize_metrics,
    "players": _sanitize_players,
    "settings": _sanitize_settings,
    "status": _sanitize_status,
    "game_data": _sanitize_game_data,
}


def _save_metrics(payload, source_clock):
    MetricSample.objects.update_or_create(
        source_clock=source_clock,
        defaults={
            "current_players": payload["currentplayernum"],
            "max_players": payload["maxplayernum"],
            "server_fps": payload["serverfps"],
            "server_fps_average": payload["serverfpsaverage"],
            "frame_time": payload["serverframetime"],
            "world_days": payload["days"],
            "base_camps": payload["basecampnum"],
            "uptime": payload["uptime"],
        },
    )


def _save_players(payload, source_clock):
    incoming = {}
    for data in payload["players"]:
        player, created = Player.objects.get_or_create(
            public_id=data["id"],
            defaults={
                "name": data["name"],
                "account_name": data["accountName"],
                "first_seen": source_clock,
                "last_seen": source_clock,
                "level": data["level"],
                "building_count": data["building_count"],
            },
        )
        if not created and source_clock >= player.last_seen:
            player.name = data["name"]
            player.account_name = data["accountName"]
            player.last_seen = source_clock
            player.level = data["level"]
            player.building_count = data["building_count"]
            player.save(
                update_fields=[
                    "name",
                    "account_name",
                    "last_seen",
                    "level",
                    "building_count",
                ]
            )
        incoming[player.id] = (player, data, created)

        if data["location_x"] != 0 or data["location_y"] != 0:
            PositionSample.objects.update_or_create(
                player=player,
                source_clock=source_clock,
                defaults={
                    "x": data["location_x"],
                    "y": data["location_y"],
                    "ping": data["ping"],
                    "level": data["level"],
                    "building_count": data["building_count"],
                },
            )

    active = {
        session.player_id: session
        for session in PlayerSession.objects.select_related("player").filter(ended_at__isnull=True)
    }

    for player_id, (player, _data, _created) in incoming.items():
        session = active.pop(player_id, None)
        if session:
            if source_clock >= session.last_seen:
                session.last_seen = source_clock
                session.save(update_fields=["last_seen"])
            continue
        PlayerSession.objects.create(
            player=player, started_at=source_clock, last_seen=source_clock
        )
        ServerEvent.objects.create(
            player=player, event_type=ServerEvent.JOIN, source_clock=source_clock
        )

    for session in active.values():
        if source_clock < session.last_seen:
            continue
        session.ended_at = source_clock
        session.save(update_fields=["ended_at"])
        ServerEvent.objects.create(
            player=session.player,
            event_type=ServerEvent.LEAVE,
            source_clock=source_clock,
        )


def cleanup_if_due():
    now = timezone.now()
    state, _ = RuntimeState.objects.get_or_create(
        key="retention-cleanup", defaults={"value": {"last": 0}}
    )
    last = int(state.value.get("last", 0))
    if now.timestamp() - last < 3600:
        return

    PositionSample.objects.filter(
        source_clock__lt=now - timedelta(days=settings.POSITION_RETENTION_DAYS)
    ).delete()
    MetricSample.objects.filter(
        source_clock__lt=now - timedelta(days=settings.METRIC_RETENTION_DAYS)
    ).delete()
    ServerEvent.objects.filter(
        source_clock__lt=now - timedelta(days=settings.METRIC_RETENTION_DAYS)
    ).delete()
    state.value = {"last": int(now.timestamp())}
    state.save(update_fields=["value", "updated_at"])


@transaction.atomic
def _close_stale_sessions(now):
    latest = LatestDataset.objects.filter(key="players").first()
    if not latest or now - latest.source_clock <= timedelta(seconds=settings.DATA_STALE_SECONDS):
        return
    for session in PlayerSession.objects.select_related("player").filter(ended_at__isnull=True):
        ended_at = session.last_seen + timedelta(seconds=settings.DATA_STALE_SECONDS)
        session.ended_at = min(ended_at, now)
        session.save(update_fields=["ended_at"])
        ServerEvent.objects.create(
            player=session.player,
            event_type=ServerEvent.LEAVE,
            source_clock=session.ended_at,
        )


@transaction.atomic
def store_dataset(dataset, value, source_clock=None):
    if dataset not in SANITIZERS:
        raise IngestError("unsupported dataset")
    source_clock = source_clock or timezone.now()
    if source_clock > timezone.now() + timedelta(minutes=5):
        raise IngestError("dataset clock is too far in the future")
    payload = SANITIZERS[dataset](value)
    current = (
        LatestDataset.objects.select_for_update()
        .filter(key=dataset)
        .first()
    )
    if current and source_clock < current.source_clock:
        return False

    LatestDataset.objects.update_or_create(
        key=dataset,
        defaults={"payload": payload, "source_clock": source_clock},
    )
    if dataset == "metrics":
        _save_metrics(payload, source_clock)
    elif dataset == "players":
        _save_players(payload, source_clock)
    return True


def run_maintenance():
    _close_stale_sessions(timezone.now())
    cleanup_if_due()
