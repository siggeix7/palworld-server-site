from datetime import timedelta
from statistics import median

from django.conf import settings
from django.db import connection
from django.db.models import Avg, Max, Min, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import (
    LatestDataset,
    MetricSample,
    Player,
    PlayerSession,
    PositionSample,
    ServerEvent,
)
from .accounts import is_site_admin


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
# Cadence-aware adaptation of RNZ01's FPS health model; see NOTICE.md.
FPS_HEALTH_WINDOW = timedelta(hours=1)
FPS_HEALTH_RECENT_WINDOW = timedelta(minutes=10)
FPS_HEALTH_STALE_AFTER = timedelta(minutes=5)
EXPECTED_METRIC_CADENCE_SECONDS = 20
FPS_HEALTH_ANCHORS = [
    (0, 0),
    (20, 10),
    (30, 25),
    (35, 40),
    (40, 50),
    (45, 60),
    (50, 75),
    (55, 90),
    (60, 100),
]
FPS_BUDGET_ANCHORS = [(0, 100), (2, 90), (5, 75), (10, 55), (15, 35), (25, 15), (40, 0)]
FPS_DIP_ANCHORS = [(0, 100), (15, 95), (30, 85), (60, 70), (90, 50), (180, 25), (300, 0)]


def _iso(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


def _duration_seconds(start, end):
    return max(0, int((end - start).total_seconds()))


def _session_end(session, now):
    if session.ended_at:
        return session.ended_at, False
    stale_end = session.last_seen + timedelta(seconds=settings.DATA_STALE_SECONDS)
    if stale_end < now:
        return stale_end, False
    return now, True


def _ramp_score(anchors, value):
    if value <= anchors[0][0]:
        return anchors[0][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if value <= x1:
            return y0 + ((value - x0) / (x1 - x0)) * (y1 - y0)
    return anchors[-1][1]


def _fps_health(rows, now):
    if not rows:
        return {
            "state": "no_data",
            "score": None,
            "label": "Nessun dato",
            "sample_count": 0,
        }

    newest_age = max(0, int((now - rows[-1][0]).total_seconds()))
    values = [row[1] for row in rows]
    deltas = [
        (current[0] - previous[0]).total_seconds()
        for previous, current in zip(rows, rows[1:])
        if current[0] > previous[0]
    ]
    cadence_deltas = [value for value in deltas if 10 <= value <= 40]
    nominal = median(cadence_deltas) if cadence_deltas else EXPECTED_METRIC_CADENCE_SECONDS
    gap_threshold = max(60, nominal * 3)
    coverage = 0.0
    weighted_fps = 0.0
    under_30 = 0.0
    longest_dip = 0.0
    current_dip = 0.0

    for index, row in enumerate(rows):
        next_delta = (
            (rows[index + 1][0] - row[0]).total_seconds()
            if index + 1 < len(rows)
            else nominal
        )
        gap_after = next_delta <= 0 or next_delta >= gap_threshold
        duration = nominal if gap_after else next_delta
        duration = max(0, duration)
        fps = row[1]
        average_fps = row[2]
        coverage += duration
        weighted_fps += (average_fps if average_fps is not None else fps) * duration
        if fps < 30:
            under_30 += duration
        if fps < 45:
            current_dip += duration
            longest_dip = max(longest_dip, current_dip)
        else:
            current_dip = 0
        if gap_after:
            current_dip = 0

    window_median = median(values)
    window_average = weighted_fps / coverage if coverage else sum(values) / len(values)
    recent_cutoff = now - FPS_HEALTH_RECENT_WINDOW
    minute_cutoff = now - timedelta(minutes=1)
    recent_values = [row[1] for row in rows if row[0] >= recent_cutoff]
    minute_values = [row[1] for row in rows if row[0] >= minute_cutoff]
    recent_median = median(recent_values) if recent_values else window_median
    minute_median = median(minute_values) if minute_values else None
    under_30_percent = (under_30 / coverage * 100) if coverage else 0
    result = {
        "state": "calibrating",
        "score": None,
        "label": "In calibrazione",
        "sample_count": len(rows),
        "coverage_seconds": round(coverage),
        "newest_sample_age_seconds": newest_age,
        "nominal_cadence_seconds": round(nominal, 2),
        "gap_threshold_seconds": round(gap_threshold, 2),
        "median_fps": round(window_median, 2),
        "recent_median_fps": round(recent_median, 2),
        "average_fps": round(window_average, 2),
        "under_30_percent": round(under_30_percent, 2),
        "longest_dip_seconds": round(longest_dip),
    }

    if newest_age > FPS_HEALTH_STALE_AFTER.total_seconds():
        result.update({"state": "stale", "label": "Dati obsoleti"})
        return result
    if coverage < 300 or len(rows) < 3:
        return result

    components = {
        "median": _ramp_score(FPS_HEALTH_ANCHORS, window_median),
        "recent": _ramp_score(FPS_HEALTH_ANCHORS, recent_median),
        "average": _ramp_score(FPS_HEALTH_ANCHORS, window_average),
        "budget": _ramp_score(FPS_BUDGET_ANCHORS, under_30_percent),
        "dip": _ramp_score(FPS_DIP_ANCHORS, longest_dip),
    }
    blend = (
        components["median"] * 0.30
        + components["recent"] * 0.25
        + components["average"] * 0.15
        + components["budget"] * 0.15
        + components["dip"] * 0.15
    )
    caps = [
        (35, minute_median is not None and minute_median < 10),
        (40, minute_median is not None and minute_median < 15),
        (25, recent_median < 25),
        (35, recent_median < 30),
        (65, recent_median < 45),
        (30, window_median < 30),
        (60, window_median < 45),
        (30, under_30_percent > 25),
        (60, under_30_percent > 10),
        (40, longest_dip > 180),
        (60, longest_dip > 90),
    ]
    score = min([blend, *[cap for cap, active in caps if active]])
    if score >= 90:
        label = "Eccellente"
    elif score >= 75:
        label = "Buono"
    elif score >= 55:
        label = "Discreto"
    elif score >= 35:
        label = "Degradato"
    else:
        label = "Critico"
    result.update(
        {
            "state": "ok",
            "score": round(score),
            "label": label,
            "components": {key: round(value, 2) for key, value in components.items()},
        }
    )
    return result


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
@never_cache
def home(request):
    return render(
        request,
        "dashboard/home.html",
        {
            "app_version": settings.APP_VERSION,
            "public_site_url": settings.PUBLIC_SITE_URL,
            "site_admin": is_site_admin(request.user),
            "palworld_access": {
                "host": settings.PALWORLD_PUBLIC_HOST,
                "port": settings.PALWORLD_PUBLIC_PORT,
                "password": settings.PALWORLD_PUBLIC_PASSWORD,
            },
        },
    )


@require_GET
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok", "version": settings.APP_VERSION})


@require_GET
@never_cache
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


def _sample_queryset(queryset, fields, max_points=720, gap_seconds=None):
    count = queryset.count()
    stride = max(1, (count + max_points - 1) // max_points)
    values = []
    previous_timestamp = None
    gap_before = False
    for index, row in enumerate(queryset.values_list(*fields).iterator(chunk_size=1000)):
        if (
            gap_seconds is not None
            and previous_timestamp is not None
            and (row[0] - previous_timestamp).total_seconds() >= gap_seconds
        ):
            gap_before = True
        if index % stride == 0 or index == count - 1:
            values.append((*row, gap_before) if gap_seconds is not None else row)
            gap_before = False
        previous_timestamp = row[0]
    return values


@require_GET
@never_cache
def history(request):
    range_name = request.GET.get("range", "24h")
    duration = RANGES.get(range_name)
    if not duration:
        return JsonResponse({"error": "unsupported range"}, status=400)

    now = timezone.now()
    since = now - duration
    queryset = MetricSample.objects.filter(
        source_clock__gte=since, source_clock__lte=now
    ).order_by("source_clock")
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
        gap_seconds=60,
    )
    health_rows = list(
        MetricSample.objects.filter(
            source_clock__gte=now - FPS_HEALTH_WINDOW, source_clock__lte=now
        )
        .order_by("source_clock")
        .values_list("source_clock", "server_fps", "server_fps_average")
    )
    return JsonResponse(
        {
            "range": range_name,
            "window": {"from": _iso(since), "to": _iso(now)},
            "fps_health": _fps_health(health_rows, now),
            "samples": [
                {
                    "timestamp": _iso(row[0]),
                    "fps": row[1],
                    "fps_average": row[2],
                    "frame_time": row[3],
                    "players": row[4],
                    "max_players": row[5],
                    "bases": row[6],
                    "gap_before": row[7],
                }
                for row in rows
            ],
        }
    )


@require_GET
@never_cache
def players(request):
    now = timezone.now()
    since_30d = now - timedelta(days=30)
    since_365d = now - timedelta(days=365)
    queryset = Player.objects.prefetch_related(
        Prefetch("sessions", queryset=PlayerSession.objects.order_by("-started_at"))
    ).order_by("-last_seen", "name")
    archive = []

    for player in queryset:
        seconds_30d = 0
        seconds_365d = 0
        seconds_all = 0
        online = False
        periods = []
        sessions = list(player.sessions.all())

        for session in sessions:
            ended_at, active = _session_end(session, now)
            seconds_all += _duration_seconds(session.started_at, ended_at)
            seconds_30d += _duration_seconds(max(session.started_at, since_30d), ended_at)
            seconds_365d += _duration_seconds(max(session.started_at, since_365d), ended_at)
            online = online or active
            periods.append(
                {
                    "started_at": _iso(session.started_at),
                    "ended_at": None if active else _iso(ended_at),
                    "active": active,
                    "duration_minutes": _duration_seconds(
                        session.started_at, ended_at
                    )
                    // 60,
                }
            )

        archive.append(
            {
                "id": player.public_id,
                "name": player.name,
                "accountName": player.account_name,
                "level": player.level,
                "first_seen": _iso(player.first_seen),
                "last_seen": _iso(player.last_seen),
                "online": online,
                "session_count": len(sessions),
                "minutes_30d": seconds_30d // 60,
                "minutes_365d": seconds_365d // 60,
                "minutes_all": seconds_all // 60,
                "periods": periods,
            }
        )

    return JsonResponse(
        {
            "generated_at": _iso(now),
            "windows": {"month_days": 30, "year_days": 365},
            "players": archive,
        }
    )


@require_GET
@never_cache
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
