from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Avg, Max, Min
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

from .models import (
    LatestDataset,
    MetricSample,
    Player,
    PlayerSession,
    PositionSample,
    ServerEvent,
)


RANGES = {
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}
TRAIL_RANGES = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


def _iso(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


def _duration_seconds(start, end):
    return max(0, int((end - start).total_seconds()))


def _dataset_map():
    return {dataset.key: dataset for dataset in LatestDataset.objects.all()}


def _session_stats(public_ids, now):
    players = {
        player.public_id: player
        for player in Player.objects.filter(public_id__in=public_ids)
    }
    since = now - timedelta(days=7)
    result = {}
    for public_id, player in players.items():
        sessions = PlayerSession.objects.filter(
            player=player,
            last_seen__gte=since,
        )
        total = 0
        current = 0
        for session in sessions:
            start = max(session.started_at, since)
            end = session.ended_at or now
            duration = _duration_seconds(start, end)
            total += duration
            if session.ended_at is None:
                current = duration
        result[public_id] = {
            "first_seen": _iso(player.first_seen),
            "last_seen": _iso(player.last_seen),
            "current_session": current,
            "online_7d": total,
        }
    return result


@require_GET
def home(request):
    return render(
        request,
        "dashboard/home.html",
        {"app_version": settings.APP_VERSION, "public_site_url": settings.PUBLIC_SITE_URL},
    )


@require_GET
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok", "version": settings.APP_VERSION})


@require_GET
def snapshot(request):
    now = timezone.now()
    datasets = _dataset_map()

    def payload(key, default):
        return datasets[key].payload if key in datasets else default

    info = payload("info", {})
    metrics = payload("metrics", {})
    players_payload = payload("players", {"players": []})
    server_settings = payload("settings", {})
    status = payload("status", {"reachable": False})
    source_times = [dataset.source_clock for dataset in datasets.values()]
    last_updated = max(source_times) if source_times else None
    metric_time = datasets.get("metrics").source_clock if datasets.get("metrics") else None
    age = int((now - metric_time).total_seconds()) if metric_time else None
    online = bool(status.get("reachable")) and age is not None and age <= settings.DATA_STALE_SECONDS
    uptime = metrics.get("uptime")
    started_at = (
        metric_time - timedelta(seconds=uptime)
        if metric_time and isinstance(uptime, (int, float))
        else None
    )

    players_time = datasets.get("players").source_clock if datasets.get("players") else None
    players_age = int((now - players_time).total_seconds()) if players_time else None
    players_stale = players_age is None or players_age > settings.DATA_STALE_SECONDS
    players = [] if players_stale else players_payload.get("players", [])
    stats = _session_stats([player["id"] for player in players], now)
    for player in players:
        player["session"] = stats.get(player["id"], {})
        x = player.get("location_x")
        y = player.get("location_y")
        player["location_available"] = (
            isinstance(x, (int, float))
            and isinstance(y, (int, float))
            and (x != 0 or y != 0)
        )

    recent_events = [
        {
            "type": event.event_type,
            "player": event.player.name,
            "player_id": event.player.public_id,
            "timestamp": _iso(event.source_clock),
        }
        for event in ServerEvent.objects.select_related("player")[:16]
    ]

    since = now - timedelta(hours=24)
    aggregates = MetricSample.objects.filter(source_clock__gte=since).aggregate(
        peak_players=Max("current_players"),
        average_players=Avg("current_players"),
        average_fps=Avg("server_fps_average"),
        minimum_fps=Min("server_fps"),
    )

    response = JsonResponse(
        {
            "status": {
                "online": online,
                "reachable": bool(status.get("reachable")),
                "stale": age is None or age > settings.DATA_STALE_SECONDS,
                "data_age_seconds": age,
                "players_stale": players_stale,
                "last_updated": _iso(last_updated),
                "started_at": _iso(started_at),
            },
            "info": info,
            "metrics": metrics,
            "players": players,
            "settings": server_settings,
            "events": recent_events,
            "summary_24h": {
                "peak_players": aggregates["peak_players"] or 0,
                "average_players": round(aggregates["average_players"] or 0, 2),
                "average_fps": round(aggregates["average_fps"] or 0, 2),
                "minimum_fps": round(aggregates["minimum_fps"] or 0, 2),
            },
            "version": settings.APP_VERSION,
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _sample_queryset(queryset, fields, max_points=720):
    count = queryset.count()
    stride = max(1, (count + max_points - 1) // max_points)
    values = []
    for index, row in enumerate(queryset.values_list(*fields).iterator(chunk_size=1000)):
        if index % stride == 0 or index == count - 1:
            values.append(row)
    return values


@require_GET
@cache_page(30)
def history(request):
    range_name = request.GET.get("range", "24h")
    duration = RANGES.get(range_name)
    if not duration:
        return JsonResponse({"error": "unsupported range"}, status=400)

    since = timezone.now() - duration
    queryset = MetricSample.objects.filter(source_clock__gte=since).order_by("source_clock")
    rows = _sample_queryset(
        queryset,
        (
            "source_clock",
            "server_fps",
            "server_fps_average",
            "frame_time",
            "current_players",
            "max_players",
            "base_camps",
        ),
    )
    return JsonResponse(
        {
            "range": range_name,
            "samples": [
                {
                    "timestamp": _iso(row[0]),
                    "fps": row[1],
                    "fps_average": row[2],
                    "frame_time": row[3],
                    "players": row[4],
                    "max_players": row[5],
                    "bases": row[6],
                }
                for row in rows
            ],
        }
    )


@require_GET
@cache_page(20)
def player_trail(request, public_id):
    range_name = request.GET.get("range", "6h")
    duration = TRAIL_RANGES.get(range_name)
    if not duration:
        return JsonResponse({"error": "unsupported range"}, status=400)

    player = get_object_or_404(Player, public_id=public_id)
    since = timezone.now() - duration
    queryset = PositionSample.objects.filter(
        player=player, source_clock__gte=since
    ).order_by("source_clock")
    rows = _sample_queryset(
        queryset,
        ("source_clock", "x", "y", "ping", "level", "building_count"),
        max_points=1000,
    )
    return JsonResponse(
        {
            "player": {"id": player.public_id, "name": player.name},
            "range": range_name,
            "positions": [
                {
                    "timestamp": _iso(row[0]),
                    "x": row[1],
                    "y": row[2],
                    "ping": row[3],
                    "level": row[4],
                    "building_count": row[5],
                }
                for row in rows
            ],
        }
    )
