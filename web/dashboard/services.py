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
    LatestDataset,
    MetricSample,
    Player,
    PlayerSession,
    PositionSample,
    RuntimeState,
    ServerEvent,
)


logger = logging.getLogger(__name__)

DATASETS = {"info", "metrics", "players", "settings", "status"}

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


def _record_dataset(record):
    tags = {
        str(entry.get("tag", "")): str(entry.get("value", ""))
        for entry in record.get("item_tags", [])
        if isinstance(entry, dict)
    }
    dataset = tags.get("dataset")
    host = record.get("host") if isinstance(record.get("host"), dict) else {}
    if settings.ZABBIX_SOURCE_HOST and host.get("host") != settings.ZABBIX_SOURCE_HOST:
        return None
    if tags.get("integration") != "palworld-site" or dataset not in DATASETS:
        return None
    return dataset


def _player_id(raw):
    identity = (
        raw.get("userId")
        or raw.get("playerId")
        or raw.get("accountName")
        or raw.get("name")
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

    players = []
    for raw in value.get("players", []):
        if not isinstance(raw, dict):
            continue
        name = _clean_text(raw.get("name"), 128)
        if not name:
            continue
        players.append(
            {
                "id": _player_id(raw),
                "name": name,
                "accountName": _clean_text(raw.get("accountName"), 128),
                "ping": round(_number(raw.get("ping")), 2),
                "location_x": _number(raw.get("location_x")),
                "location_y": _number(raw.get("location_y")),
                "level": _integer(raw.get("level")),
                "building_count": _integer(raw.get("building_count")),
            }
        )
    players.sort(key=lambda player: player["name"].casefold())
    return {"players": players}


def _sanitize_status(value):
    if isinstance(value, str):
        value = value.strip().lower()
    return {"reachable": value in (1, 1.0, True, "1", "true", "up")}


SANITIZERS = {
    "info": _sanitize_info,
    "metrics": _sanitize_metrics,
    "players": _sanitize_players,
    "settings": _sanitize_settings,
    "status": _sanitize_status,
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


def _cleanup_if_due():
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
def _process_record(record):
    if not isinstance(record, dict):
        raise IngestError("each NDJSON line must contain an object")
    dataset = _record_dataset(record)
    if not dataset:
        return None

    source_clock = _source_time(record)
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

    _close_stale_sessions(timezone.now())
    for index, record in enumerate(records, start=1):
        try:
            dataset = _process_record(record)
        except IngestError as exc:
            rejected += 1
            errors.append(f"record {index}: {exc}")
            continue
        if dataset is None:
            ignored += 1
            continue
        datasets.add(dataset)
        accepted += 1

    _cleanup_if_due()
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
    }
