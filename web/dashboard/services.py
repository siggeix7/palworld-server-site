import hashlib
import hmac
import json
import logging
import math
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import (
    ConnectorBatch,
    LatestDataset,
    MetricSample,
    Player,
    PlayerSession,
    PositionSample,
    RuntimeState,
    ServerEvent,
    VmMetricSample,
)
from .vm_metrics import VM_METRICS


logger = logging.getLogger(__name__)

DATASETS = {"game_data", "info", "metrics", "players", "settings", "status"}

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


def _source_time(record):
    try:
        seconds = int(record["clock"])
        nanoseconds = int(record.get("ns", 0))
    except (KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
        raise IngestError("record clock is missing or invalid") from exc
    try:
        value = datetime.fromtimestamp(seconds, tz=dt_timezone.utc).replace(
            microsecond=max(0, min(999999, nanoseconds // 1000))
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise IngestError("record clock is outside the supported range") from exc
    if value > timezone.now() + timedelta(minutes=5):
        raise IngestError("record clock is too far in the future")
    return value


def _record_route(record):
    item_tags = record.get("item_tags")
    if not isinstance(item_tags, list):
        return None, None
    tags = {
        str(entry.get("tag", "")): str(entry.get("value", ""))
        for entry in item_tags
        if isinstance(entry, dict)
    }
    dataset = tags.get("dataset")
    host = record.get("host") if isinstance(record.get("host"), dict) else {}
    if settings.ZABBIX_SOURCE_HOST and host.get("host") != settings.ZABBIX_SOURCE_HOST:
        return None, None
    if tags.get("integration") != "palworld-site":
        return None, None
    if dataset in DATASETS:
        return dataset, None
    metric = tags.get("metric")
    if dataset == "vm" and metric in VM_METRICS:
        return "vm", metric
    return None, None


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

    # Field aliases follow RNZ01's payload normalizer; raw IDs remain HMAC inputs only.
    # Adapted from lib/palworld.ts at upstream commit 588fa639; see NOTICE.md.
    players = []
    for raw in value.get("players", []):
        if not isinstance(raw, dict):
            continue
        name = _clean_text(raw.get("name") or raw.get("nickname"), 128)
        if not name:
            continue
        players.append(
            {
                "id": _player_id(raw),
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


# Mirrors MAP_BOUNDS in management/commands/build_map_catalogue.py so live world
# objects are projected onto the same Palpagos / World Tree regions.
WORLD_MAP_BOUNDS = {
    "palpagos": {
        "min_x": -1099400,
        "max_x": 349400,
        "min_y": -724400,
        "max_y": 724400,
    },
    "world-tree": {
        "min_x": 347351.5,
        "max_x": 689148.5,
        "min_y": -818197,
        "max_y": -476400,
    },
}

MAX_WORLD_OBJECTS = 20000

# Players and bases come from the players dataset and guild sync respectively,
# so the live world feed only contributes these four actor kinds.
INCLUDED_WORLD_KINDS = {"wild-pals", "npcs", "companions", "workers"}

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


def _humanize_class(class_name):
    text = "" if class_name is None else str(class_name)
    if text.startswith("BP_"):
        text = text[3:]
    if text.endswith("_C"):
        text = text[:-2]
    return text.replace("_", " ").strip()


def _classify_world_actor(actor):
    for field in ("UnitType", "Type"):
        value = actor.get(field)
        if not isinstance(value, str):
            continue
        kind = _ACTOR_KIND_MAP.get(value.strip().lower())
        if kind:
            return kind
    return None


def _is_active_value(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    return False


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

    # First pass: build InstanceID -> public_player_id map from player actors so
    # companions can be linked to their owning player without exposing raw IDs.
    player_id_map = {}
    for actor in actor_data:
        if not isinstance(actor, dict):
            continue
        if _classify_world_actor(actor) != "players":
            continue
        instance_id = actor.get("InstanceID")
        userid = actor.get("userid")
        if not isinstance(instance_id, str) or not instance_id:
            continue
        if not isinstance(userid, str) or not userid:
            continue
        player_id_map[instance_id] = _player_id({"userId": userid})

    # Second pass: classify, filter active/in-bounds actors, hash IDs, sanitize
    # free text and cap the payload so very large worlds stay bounded.
    objects = []
    truncated = False
    for actor in actor_data:
        if len(objects) >= MAX_WORLD_OBJECTS:
            truncated = True
            break
        if not isinstance(actor, dict):
            continue
        kind = _classify_world_actor(actor)
        if kind not in INCLUDED_WORLD_KINDS:
            continue
        if not _is_active_value(actor.get("IsActive")):
            continue
        x = _number(actor.get("LocationX"))
        y = _number(actor.get("LocationY"))
        if x == 0 and y == 0:
            continue
        map_id = _map_for_coords(x, y)
        if map_id is None:
            continue
        instance_id = actor.get("InstanceID")
        if not isinstance(instance_id, str) or not instance_id:
            continue
        nick_name = _clean_text(actor.get("NickName"), 128)
        class_name = _humanize_class(actor.get("Class"))
        name = nick_name or class_name or kind
        obj = {
            "id": _world_object_id(instance_id, kind),
            "kind": kind,
            "name": name,
            "x": round(x, 2),
            "y": round(y, 2),
            "map": map_id,
        }
        if class_name and class_name != name:
            obj["detail"] = class_name
        level = _integer(actor.get("Level"))
        if level > 0:
            obj["level"] = level
        if kind == "companions":
            trainer_id = actor.get("TrainerInstanceID")
            if isinstance(trainer_id, str):
                owner_id = player_id_map.get(trainer_id)
                if owner_id:
                    obj["owner_id"] = owner_id
        guild_name = _clean_text(actor.get("GuildName"), 128)
        if guild_name:
            obj["guild_name"] = guild_name
        objects.append(obj)

    return {"objects": objects, "count": len(objects), "truncated": truncated}


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


def _save_vm_metric(record, metric, source_clock):
    try:
        value_type = int(record.get("type"))
        value = float(record.get("value"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise IngestError(f"VM metric {metric} must be numeric") from exc
    if value_type not in {0, 3}:
        raise IngestError(f"VM metric {metric} has unsupported value type")
    if not math.isfinite(value) or abs(value) > 1e18:
        raise IngestError(f"VM metric {metric} is outside the supported range")
    VmMetricSample.objects.update_or_create(
        metric=metric,
        source_clock=source_clock,
        defaults={"value": value},
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
    VmMetricSample.objects.filter(
        source_clock__lt=now - timedelta(days=settings.METRIC_RETENTION_DAYS)
    ).delete()
    ConnectorBatch.objects.filter(
        received_at__lt=now
        - timedelta(days=settings.CONNECTOR_AUDIT_RETENTION_DAYS)
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
def _process_record(record):
    if not isinstance(record, dict):
        raise IngestError("each NDJSON line must contain an object")
    dataset, metric = _record_route(record)
    if not dataset:
        return None

    source_clock = _source_time(record)
    if dataset == "vm":
        _save_vm_metric(record, metric, source_clock)
        return dataset
    payload = SANITIZERS[dataset](record.get("value"))
    current = LatestDataset.objects.select_for_update().filter(key=dataset).first()
    if current and source_clock < current.source_clock:
        return None

    LatestDataset.objects.update_or_create(
        key=dataset,
        defaults={"payload": payload, "source_clock": source_clock},
    )
    if dataset == "metrics":
        _save_metrics(payload, source_clock)
    elif dataset == "players":
        _save_players(payload, source_clock)
    return dataset


def process_records(records):
    accepted = 0
    ignored = 0
    rejected = 0
    errors = []
    datasets = set()
    source_hosts = set()
    ignored_items = []

    _close_stale_sessions(timezone.now())
    for index, record in enumerate(records, start=1):
        source_allowed = False
        if isinstance(record, dict) and isinstance(record.get("host"), dict):
            source_host = _clean_text(record["host"].get("host"), 128)
            source_allowed = source_host == settings.ZABBIX_SOURCE_HOST
            if source_allowed:
                source_hosts.add(source_host)
        try:
            dataset = _process_record(record)
        except IngestError as exc:
            rejected += 1
            errors.append(f"record {index}: {exc}")
            continue
        if dataset is None:
            ignored += 1
            if source_allowed and len(ignored_items) < 10 and isinstance(record, dict):
                ignored_items.append(_clean_text(record.get("name"), 160))
            continue
        datasets.add(dataset)
        accepted += 1

    cleanup_if_due()
    logger.info(
        "Zabbix batch accepted=%s ignored=%s rejected=%s datasets=%s",
        accepted,
        ignored,
        rejected,
        ",".join(sorted(datasets)) or "none",
    )
    return {
        "accepted": accepted,
        "ignored": ignored,
        "rejected": rejected,
        "errors": errors[:10],
        "datasets": sorted(datasets),
        "source_hosts": sorted(source_hosts)[:8],
        "ignored_items": [name for name in ignored_items if name],
    }


def record_connector_batch(result, record_count):
    ConnectorBatch.objects.create(
        record_count=max(0, int(record_count)),
        accepted=max(0, int(result.get("accepted", 0))),
        ignored=max(0, int(result.get("ignored", 0))),
        rejected=max(0, int(result.get("rejected", 0))),
        datasets=list(result.get("datasets", []))[:16],
        source_hosts=list(result.get("source_hosts", []))[:8],
        ignored_items=list(result.get("ignored_items", []))[:10],
    )
