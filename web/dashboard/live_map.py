import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.db.models import OuterRef, Subquery
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import GuildSnapshot, LatestDataset, Player, PositionSample
from .services import WORLD_MAP_BOUNDS


UPSTREAM_REVISION = "19f3e3f8e684481bde58fef6c76845f811d57614"
CATALOGUE_PATH = Path(settings.BASE_DIR) / "dashboard/data/live-map-catalogue.json"
CATALOGUE_METADATA = {
    "gameVersion": "1.0.1.100619",
    "generator": "palworld-asset-exporter/4",
    "decoder": "CUE4Parse/1.2.2.202607",
}
SAVE_STALE_AFTER = timedelta(minutes=15)
WORLD_OBJECT_KINDS = {
    "bases",
    "workers",
    "companions",
    "wild-pals",
    "npcs",
}


def _iso(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


def _is_stale(timestamp, seconds):
    return timestamp is None or timezone.now() - timestamp > timedelta(seconds=seconds)


def _map_for_coordinates(x, y):
    for map_id, bounds in WORLD_MAP_BOUNDS.items():
        if (
            bounds["min_x"] <= x <= bounds["max_x"]
            and bounds["min_y"] <= y <= bounds["max_y"]
        ):
            return map_id
    return None


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _coordinates(payload):
    x = _number(payload.get("location_x"))
    y = _number(payload.get("location_y"))
    if x is None or y is None or (x == 0 and y == 0):
        return None
    return x, y


def _snapshot_payload():
    snapshot = GuildSnapshot.objects.first()
    payload = snapshot.payload if snapshot and isinstance(snapshot.payload, dict) else {}
    return snapshot, payload


def _guild_data(save_payload, game_payload):
    guild_names = {}
    for guild in save_payload.get("guilds", []):
        if not isinstance(guild, dict):
            continue
        guild_id = guild.get("group_id")
        guild_name = str(guild.get("guild_name", "")).strip()
        if isinstance(guild_id, str) and guild_id:
            guild_names[guild_id] = guild_name

    saved_by_name = defaultdict(list)
    for player in save_payload.get("players", []):
        if not isinstance(player, dict):
            continue
        name = str(player.get("player_name", "")).strip().casefold()
        if name:
            saved_by_name[name].append(player)

    live_keys_by_name = defaultdict(set)
    for item in game_payload.get("objects", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("guild_name", "")).strip().casefold()
        key = item.get("guild_key")
        if name and isinstance(key, str) and key:
            live_keys_by_name[name].add(key)

    return guild_names, saved_by_name, live_keys_by_name


@lru_cache(maxsize=1)
def _catalogue_asset():
    data = CATALOGUE_PATH.read_bytes()
    payload = json.loads(data)
    if (
        not isinstance(payload, dict)
        or any(payload.get(key) != value for key, value in CATALOGUE_METADATA.items())
        or not isinstance(payload.get("locations"), list)
    ):
        raise ValueError("live map catalogue has an invalid schema or provenance")
    return data, hashlib.sha256(data).hexdigest()


@require_GET
@never_cache
def page(request):
    return render(
        request,
        "dashboard/map.html",
        {"app_version": settings.APP_VERSION},
    )


@require_GET
@never_cache
def config(request):
    _, catalogue_hash = _catalogue_asset()
    response = JsonResponse(
        {
            "pollIntervalMs": settings.PALWORLD_API_INTERVALS["players"] * 1000,
            "worldPollIntervalMs": settings.PALWORLD_API_INTERVALS["game_data"] * 1000,
            "worldDataEnabled": True,
            "layers": [
                {
                    "id": "palpagos",
                    "name": "Palpagos",
                    "imageUrl": static("dashboard/live-map/maps/palpagos.jpg"),
                    "bounds": [349400, 724400, -1099400, -724400],
                },
                {
                    "id": "world-tree",
                    "name": "World Tree",
                    "imageUrl": static("dashboard/live-map/maps/world-tree.jpg"),
                    "bounds": [689148.5, -476400, 347351.5, -818197],
                },
            ],
            "catalogueUrl": (
                f"{reverse('live-map-catalogue')}?v={catalogue_hash}"
            ),
            "landmarks": [],
            "landmarkCatalogue": CATALOGUE_METADATA,
            "upstreamRevision": UPSTREAM_REVISION,
        }
    )
    response.headers["Cache-Control"] = "no-store, private"
    return response


@require_GET
def catalogue(request):
    data, catalogue_hash = _catalogue_asset()
    etag = f'"{catalogue_hash}"'
    if request.headers.get("If-None-Match") == etag:
        response = HttpResponse(status=304)
    else:
        response = HttpResponse(data, content_type="application/json")
    response.headers["ETag"] = etag
    response.headers["Vary"] = "Accept-Encoding"
    if request.GET.get("v") == catalogue_hash:
        response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    else:
        response.headers["Cache-Control"] = "no-cache, private"
    return response


@require_GET
@never_cache
def players(request):
    datasets = {
        dataset.key: dataset
        for dataset in LatestDataset.objects.filter(
            key__in=("game_data", "info", "metrics", "players", "status")
        )
    }
    players_dataset = datasets.get("players")
    metrics_dataset = datasets.get("metrics")
    players_stale = _is_stale(
        players_dataset.source_clock if players_dataset else None,
        settings.DATA_STALE_SECONDS,
    )
    metrics_stale = _is_stale(
        metrics_dataset.source_clock if metrics_dataset else None,
        settings.DATA_STALE_SECONDS,
    )
    status_dataset = datasets.get("status")
    status_payload = status_dataset.payload if status_dataset else {}
    status_is_newer = bool(
        status_dataset
        and players_dataset
        and status_dataset.source_clock >= players_dataset.source_clock
    )
    reachable = bool(status_payload.get("reachable")) or bool(
        players_dataset and not players_stale and not status_is_newer
    )
    connected = bool(players_dataset and reachable and not players_stale)

    live_players = (
        (players_dataset.payload or {}).get("players", [])
        if players_dataset and not players_stale
        else []
    )
    live_by_id = {
        item.get("id"): item
        for item in live_players
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }

    latest_position = PositionSample.objects.filter(player_id=OuterRef("pk")).order_by(
        "-source_clock", "-id"
    )
    player_rows = list(
        Player.objects.annotate(
            latest_x=Subquery(latest_position.values("x")[:1]),
            latest_y=Subquery(latest_position.values("y")[:1]),
        ).order_by("name", "public_id")
    )
    name_counts = Counter(player.name.strip().casefold() for player in player_rows)

    save_snapshot, save_payload = _snapshot_payload()
    game_payload = datasets.get("game_data").payload if datasets.get("game_data") else {}
    guild_names, saved_by_name, live_keys_by_name = _guild_data(
        save_payload, game_payload or {}
    )

    public_players = []
    for player in player_rows:
        live = live_by_id.get(player.public_id)
        position = _coordinates(live) if live else None
        if position is None and not live:
            position = (
                (player.latest_x, player.latest_y)
                if player.latest_x is not None and player.latest_y is not None
                else None
            )
        if position is None:
            continue
        x, y = position
        map_id = _map_for_coordinates(x, y)
        if not map_id:
            continue

        normalized_name = player.name.strip().casefold()
        saved_matches = saved_by_name.get(normalized_name, [])
        saved = (
            saved_matches[0]
            if len(saved_matches) == 1 and name_counts[normalized_name] == 1
            else None
        )
        saved_guild_id = saved.get("guild_id", "") if saved else ""
        guild_name = guild_names.get(saved_guild_id, "")
        live_guild_keys = live_keys_by_name.get(guild_name.casefold(), set())
        guild_key = (
            next(iter(live_guild_keys))
            if len(live_guild_keys) == 1
            else saved_guild_id
        )
        level = max(
            player.level,
            int(live.get("level", 0)) if live else 0,
            int(saved.get("level", 0)) if saved else 0,
        )
        item = {
            "id": player.public_id,
            "name": player.name,
            "level": level,
            "online": bool(connected and live),
            "lastSeenAt": _iso(player.last_seen),
            "x": x,
            "y": y,
            "map": map_id,
        }
        if guild_key:
            item["guildKey"] = guild_key
        if guild_name:
            item["guildName"] = guild_name
        public_players.append(item)

    info = datasets.get("info").payload if datasets.get("info") else {}
    metrics = metrics_dataset.payload if metrics_dataset else {}
    response_payload = {
        "server": {
            "name": info.get("servername") or "Palworld Server Observatory",
            "description": info.get("description") or "",
            "version": info.get("version") or "",
        },
        "metrics": {
            "currentPlayers": metrics.get("currentplayernum", 0),
            "maxPlayers": metrics.get("maxplayernum", 0),
            "serverFps": metrics.get("serverfps", 0),
            "serverFrameTime": metrics.get("serverframetime", 0),
            "uptimeSeconds": metrics.get("uptime", 0),
            "baseCount": metrics.get("basecampnum", 0),
            "days": metrics.get("days", 0),
        },
        "metricsAvailable": bool(metrics_dataset),
        "metricsStale": metrics_stale,
        "connected": connected,
        "stale": players_stale or not reachable,
        "saveEnabled": True,
        "saveAvailable": bool(save_snapshot),
        "saveStale": (
            not save_snapshot
            or timezone.now() - save_snapshot.updated_at > SAVE_STALE_AFTER
        ),
        "players": public_players,
    }
    if metrics_dataset:
        response_payload["metricsUpdatedAt"] = _iso(metrics_dataset.source_clock)
    if players_dataset:
        response_payload["lastSuccessAt"] = _iso(players_dataset.source_clock)
    if save_snapshot:
        response_payload["saveUpdatedAt"] = _iso(save_snapshot.updated_at)
        response_payload["saveSnapshotAt"] = _iso(save_snapshot.updated_at)
    response = JsonResponse(response_payload)
    response.headers["Cache-Control"] = "no-store, private"
    return response


@require_GET
@never_cache
def objects(request):
    dataset = LatestDataset.objects.filter(key="game_data").first()
    payload = dataset.payload if dataset and isinstance(dataset.payload, dict) else {}
    known_player_ids = set()
    if any(
        isinstance(source, dict)
        and source.get("kind") == "companions"
        and isinstance(source.get("owner_ids"), list)
        for source in payload.get("objects", [])
    ):
        known_player_ids = set(Player.objects.values_list("public_id", flat=True))
    public_objects = []
    for source in payload.get("objects", []):
        if not isinstance(source, dict) or source.get("kind") not in WORLD_OBJECT_KINDS:
            continue
        x = _number(source.get("x"))
        y = _number(source.get("y"))
        if x is None or y is None or not _map_for_coordinates(x, y):
            continue
        item = {
            "id": source.get("id"),
            "kind": source["kind"],
            "name": source.get("name") or "Map object",
            "x": x,
            "y": y,
            "map": source.get("map") or _map_for_coordinates(x, y),
        }
        for source_key, public_key in (
            ("detail", "detail"),
            ("base_id", "baseId"),
            ("guild_key", "guildKey"),
            ("guild_name", "guildName"),
            ("level", "level"),
        ):
            if source.get(source_key) not in (None, "", 0):
                item[public_key] = source[source_key]
        owner_candidates = source.get("owner_ids")
        if isinstance(owner_candidates, list):
            owner_id = next(
                (
                    candidate
                    for candidate in owner_candidates
                    if candidate in known_player_ids
                ),
                source.get("owner_id"),
            )
        else:
            owner_id = source.get("owner_id")
        if owner_id:
            item["ownerId"] = owner_id
        public_objects.append(item)

    available = bool(dataset)
    stale = _is_stale(
        dataset.source_clock if dataset else None,
        settings.WORLD_DATA_STALE_SECONDS,
    )
    response_payload = {
        "enabled": True,
        "available": available,
        "stale": stale,
        "unsupported": False,
        "truncated": bool(payload.get("truncated", False)),
        "total": payload.get("supported_count", len(public_objects)),
        "objects": public_objects,
    }
    if dataset:
        response_payload["updatedAt"] = _iso(dataset.source_clock)
    else:
        response_payload["lastError"] = "refresh-failed"
    response = JsonResponse(response_payload)
    response.headers["Cache-Control"] = "no-store, private"
    return response
