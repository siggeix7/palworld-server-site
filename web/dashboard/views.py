import re
from collections import Counter, defaultdict
from datetime import timedelta
from statistics import median

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Avg, Count, Max, Min, Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import (
    GuildSnapshot,
    LatestDataset,
    MetricSample,
    Player,
    PlayerSession,
    PositionSample,
    ServerEvent,
)
# Server-side cache TTL for heavy read-only aggregations. The collector refreshes
# the underlying data every 15-30s, so a 5s cache is invisible to users while
# collapsing redundant work across concurrent dashboard clients.
API_CACHE_TTL = 5


def _cached_payload(key, compute):
    payload = cache.get(key)
    if payload is None:
        payload = compute()
        cache.set(key, payload, API_CACHE_TTL)
    return payload


RANGES = {
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
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
    sessions_by_player = defaultdict(list)
    for session in (
        PlayerSession.objects.filter(
            player__public_id__in=public_ids,
            last_seen__gte=since,
        )
        .select_related("player")
        .only("player__public_id", "started_at", "last_seen", "ended_at")
        .order_by("player__public_id")
    ):
        sessions_by_player[session.player.public_id].append(session)
    result = {}
    for public_id, player in players.items():
        total = 0
        current = 0
        for session in sessions_by_player.get(public_id, ()):
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
def terms_page(request):
    return render(
        request,
        "dashboard/terms.html",
        {
            "canonical_url": (
                f"{settings.PUBLIC_SITE_URL}{request.path}"
                if settings.PUBLIC_SITE_URL
                else ""
            ),
            "terms_version": settings.CURRENT_TERMS_VERSION,
            "terms_effective_date": settings.CURRENT_TERMS_EFFECTIVE_DATE,
            "privacy_controller_name": settings.PRIVACY_CONTROLLER_NAME,
            "privacy_contact_email": settings.PRIVACY_CONTACT_EMAIL,
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
    def compute():
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
        players = [dict(p) for p in (players_payload.get("players", []) if not players_stale else [])]
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

        return {
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

    response = JsonResponse(_cached_payload("snapshot:v1", compute))
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


def _compute_players_archive():
    now = timezone.now()
    since_30d = now - timedelta(days=30)
    since_365d = now - timedelta(days=365)
    session_window = now - timedelta(days=settings.SESSION_RETENTION_DAYS)
    queryset = Player.objects.prefetch_related(
        Prefetch(
            "sessions",
            queryset=PlayerSession.objects.filter(started_at__gte=session_window).order_by("-started_at"),
        )
    ).order_by("-last_seen", "name")
    archive = []

    snapshot = GuildSnapshot.objects.first()
    save_payload = (
        snapshot.payload
        if snapshot and isinstance(snapshot.payload, dict)
        else {}
    )
    saved_players = save_payload.get("players", [])
    if not isinstance(saved_players, list):
        saved_players = []
    saved_guilds = save_payload.get("guilds", [])
    if not isinstance(saved_guilds, list):
        saved_guilds = []
    guild_names = {
        guild.get("group_id"): guild.get("guild_name", "")
        for guild in saved_guilds
        if isinstance(guild, dict)
    }
    valid_saved_players = []
    saved_by_name = defaultdict(list)
    for saved_player in saved_players:
        if not isinstance(saved_player, dict):
            continue
        saved_id = saved_player.get("player_id")
        normalized_name = str(saved_player.get("player_name", "")).strip().casefold()
        if not isinstance(saved_id, str) or not saved_id or not normalized_name:
            continue
        valid_saved_players.append(saved_player)
        saved_by_name[normalized_name].append(saved_player)
    saved_players = valid_saved_players
    telemetry_name_counts = Counter(
        player.name.strip().casefold() for player in queryset
    )
    consumed_saved_ids = set()

    ping_stats = {
        row["player_id"]: {
            "average": round(row["average"] or 0, 2),
            "minimum": round(row["minimum"] or 0, 2),
            "maximum": round(row["maximum"] or 0, 2),
            "sample_count": row["sample_count"],
        }
        for row in PositionSample.objects.filter(
            source_clock__gte=now - timedelta(days=7),
            source_clock__lte=now,
            ping__gt=0,
        )
        .values("player_id")
        .annotate(
            average=Avg("ping"),
            minimum=Min("ping"),
            maximum=Max("ping"),
            sample_count=Count("id"),
        )
    }

    def save_fields(saved_player):
        if not saved_player:
            return {
                "save_available": False,
                "save_only": False,
                "saved_level": None,
                "exp": None,
                "owned_pal_count": None,
                "unused_status_points": None,
                "status_points": {},
                "guild_name": "",
                "is_guild_admin": False,
            }
        return {
            "save_available": True,
            "save_only": False,
            "saved_level": saved_player.get("level", 0),
            "exp": saved_player.get("exp", 0),
            "owned_pal_count": saved_player.get("owned_pal_count", 0),
            "unused_status_points": saved_player.get(
                "unused_status_points", 0
            ),
            "status_points": saved_player.get("status_points", {}),
            "guild_name": guild_names.get(saved_player.get("guild_id"), ""),
            "is_guild_admin": bool(saved_player.get("is_admin", False)),
        }

    for player in queryset:
        seconds_30d = 0
        seconds_365d = 0
        online = False
        periods = []
        open_seconds = 0
        open_longest = 0
        active_dates_30d = set()
        sessions = list(player.sessions.all())

        for session in sessions:
            ended_at, active = _session_end(session, now)
            duration = _duration_seconds(session.started_at, ended_at)
            seconds_30d += _duration_seconds(max(session.started_at, since_30d), ended_at)
            seconds_365d += _duration_seconds(max(session.started_at, since_365d), ended_at)
            online = online or active
            if session.ended_at is None:
                open_seconds += duration
                open_longest = max(open_longest, duration)
            active_start = max(session.started_at, since_30d)
            if ended_at > active_start:
                day = timezone.localdate(active_start)
                final_day = timezone.localdate(ended_at - timedelta(microseconds=1))
                while day <= final_day:
                    active_dates_30d.add(day)
                    day += timedelta(days=1)
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

        seconds_all = player.minutes_lifetime * 60 + open_seconds
        session_count = player.session_count_lifetime
        longest_session = max(player.longest_session_minutes * 60, open_longest)

        normalized_name = player.name.strip().casefold()
        matches = saved_by_name.get(normalized_name, [])
        saved_player = (
            matches[0]
            if len(matches) == 1 and telemetry_name_counts[normalized_name] == 1
            else None
        )
        if saved_player:
            consumed_saved_ids.add(saved_player["player_id"])
        progression = save_fields(saved_player)

        archive.append(
            {
                "id": player.public_id,
                "name": player.name,
                "accountName": player.account_name,
                "level": max(player.level, progression["saved_level"] or 0),
                "building_count": player.building_count,
                "first_seen": _iso(player.first_seen),
                "last_seen": _iso(player.last_seen),
                "online": online,
                "session_count": session_count,
                "minutes_30d": seconds_30d // 60,
                "minutes_365d": seconds_365d // 60,
                "minutes_all": seconds_all // 60,
                "average_session_minutes": (
                    round(seconds_all / 60 / session_count) if session_count else 0
                ),
                "longest_session_minutes": longest_session // 60,
                "active_days_30d": len(active_dates_30d),
                "ping_7d": ping_stats.get(player.id),
                "periods": periods,
                **progression,
            }
        )

    for saved_player in saved_players:
        if (
            not isinstance(saved_player, dict)
            or saved_player.get("player_id") in consumed_saved_ids
        ):
            continue
        progression = save_fields(saved_player)
        progression["save_only"] = True
        archive.append(
            {
                "id": f"save-{saved_player['player_id']}",
                "name": saved_player["player_name"],
                "accountName": "",
                "level": saved_player.get("level", 0),
                "building_count": 0,
                "first_seen": None,
                "last_seen": None,
                "online": False,
                "session_count": 0,
                "minutes_30d": 0,
                "minutes_365d": 0,
                "minutes_all": 0,
                "average_session_minutes": 0,
                "longest_session_minutes": 0,
                "active_days_30d": 0,
                "ping_7d": None,
                "periods": [],
                **progression,
            }
        )

    archive.sort(key=lambda player: player["name"].casefold())

    return {
        "generated_at": _iso(now),
        "windows": {"month_days": 30, "year_days": 365},
        "save_updated_at": _iso(snapshot.updated_at) if snapshot else None,
        "players": archive,
    }


@require_GET
@never_cache
def players(request):
    response = JsonResponse(_cached_payload("players:v1", _compute_players_archive))
    response.headers["Cache-Control"] = "no-store"
    return response


PLAYER_SESSION_LIST_LIMIT = 30
PLAYER_PING_POINTS = 240
PLAYER_PRESENCE_WEEKS = 8
PLAYER_PUBLIC_ID_PATTERN = re.compile(r"^[0-9a-f]{24}\Z")


def _player_ping_series(player, now):
    since = now - timedelta(days=settings.POSITION_RETENTION_DAYS)
    queryset = PositionSample.objects.filter(
        player=player,
        source_clock__gte=since,
        source_clock__lte=now,
        ping__gt=0,
    ).order_by("source_clock")
    rows = _sample_queryset(
        queryset,
        ("source_clock", "ping"),
        max_points=PLAYER_PING_POINTS,
    )
    return [{"timestamp": _iso(row[0]), "ping": round(row[1], 1)} for row in rows]


def _player_presence_grid(player, now):
    start = now - timedelta(weeks=PLAYER_PRESENCE_WEEKS)
    grid = [[0.0] * 24 for _ in range(7)]
    ended = list(
        PlayerSession.objects.filter(
            player=player, started_at__lt=now, ended_at__gt=start
        )
    )
    open_sessions = list(
        PlayerSession.objects.filter(player=player, started_at__lt=now, ended_at__isnull=True)
    )
    for session in ended + open_sessions:
        stale_end = session.last_seen + timedelta(seconds=settings.DATA_STALE_SECONDS)
        end = session.ended_at or min(now, stale_end)
        span_start = max(session.started_at, start)
        if end <= span_start:
            continue
        cursor = span_start
        while cursor < end:
            next_hour = min(
                end,
                cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1),
            )
            minutes = (next_hour - cursor).total_seconds() / 60
            grid[timezone.localdate(cursor).weekday()][cursor.hour] += minutes
            cursor = next_hour
    return [[round(cell / PLAYER_PRESENCE_WEEKS) for cell in row] for row in grid]


def _compute_player_detail(public_id):
    now = timezone.now()
    try:
        player = Player.objects.get(public_id=public_id)
    except Player.DoesNotExist:
        return None
    sessions = list(
        PlayerSession.objects.filter(player=player).order_by("-started_at")[:PLAYER_SESSION_LIST_LIMIT]
    )
    active_session = PlayerSession.objects.filter(player=player, ended_at__isnull=True).first()
    current_session = None
    if active_session:
        ended_at, _ = _session_end(active_session, now)
        current_session = _duration_seconds(active_session.started_at, ended_at)
    return {
        "player": {
            "public_id": player.public_id,
            "name": player.name,
            "account_name": player.account_name,
            "level": player.level,
            "building_count": player.building_count,
            "first_seen": _iso(player.first_seen),
            "last_seen": _iso(player.last_seen),
            "online": active_session is not None,
            "current_session": current_session,
            "minutes_lifetime": player.minutes_lifetime,
            "session_count_lifetime": player.session_count_lifetime,
            "longest_session_minutes": player.longest_session_minutes,
        },
        "sessions": [
            {
                "started_at": _iso(session.started_at),
                "ended_at": None if session.ended_at is None else _iso(session.ended_at),
                "active": session.ended_at is None,
                "duration_minutes": _duration_seconds(
                    session.started_at, _session_end(session, now)[0]
                )
                // 60,
            }
            for session in sessions
        ],
        "ping": _player_ping_series(player, now),
        "presence": {
            "weeks": PLAYER_PRESENCE_WEEKS,
            "rows": 7,
            "cols": 24,
            "grid": _player_presence_grid(player, now),
        },
        "events": [
            {"type": event.event_type, "timestamp": _iso(event.source_clock)}
            for event in ServerEvent.objects.filter(player=player)[:20]
        ],
        "generated_at": _iso(now),
    }


@require_GET
@never_cache
def player_detail(request, public_id):
    if not PLAYER_PUBLIC_ID_PATTERN.fullmatch(public_id):
        return JsonResponse({"error": "player not found"}, status=404)
    payload = _cached_payload(f"player:{public_id}:v1", lambda: _compute_player_detail(public_id))
    if payload is None:
        return JsonResponse({"error": "player not found"}, status=404)
    response = JsonResponse(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


ACTIVITY_RANGES = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}
LEADERBOARD_LIMIT = 20
NOMINAL_CADENCE = 20
DATA_GAP_THRESHOLD = 60
WEEKDAY_LABELS = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]

# Vanilla Palworld defaults (factual game settings, not creative content).
VANILLA_DEFAULTS = {
    "Difficulty": "Normal",
    "DayTimeSpeedRate": 1.0,
    "NightTimeSpeedRate": 1.0,
    "ExpRate": 1.0,
    "PalCaptureRate": 1.0,
    "PalSpawnNumRate": 1.0,
    "PalDamageRateAttack": 1.0,
    "PalDamageRateDefense": 1.0,
    "PlayerDamageRateAttack": 1.0,
    "PlayerDamageRateDefense": 1.0,
    "PlayerStomachDecreaceRate": 1.0,
    "PlayerStaminaDecreaceRate": 1.0,
    "PlayerAutoHPRegeneRate": 1.0,
    "PlayerAutoHpRegeneRateInSleep": 1.0,
    "PalStomachDecreaceRate": 1.0,
    "PalStaminaDecreaceRate": 1.0,
    "PalAutoHPRegeneRate": 1.0,
    "PalAutoHpRegeneRateInSleep": 1.0,
    "CollectionDropRate": 1.0,
    "CollectionObjectHpRate": 1.0,
    "CollectionObjectRespawnSpeedRate": 1.0,
    "EnemyDropItemRate": 1.0,
    "DropItemMaxNum": 3000,
    "DropItemAliveMaxHours": 6.0,
    "WorkSpeedRate": 1.0,
    "PalEggDefaultHatchingTime": 72.0,
    "BaseCampMaxNum": 128,
    "BaseCampWorkerMaxNum": 15,
    "GuildPlayerMaxNum": 20,
    "ServerPlayerMaxNum": 32,
    "CoopPlayerMaxNum": 4,
    "bIsPvP": False,
    "bEnablePlayerToPlayerDamage": False,
    "bEnableFriendlyFire": False,
    "bEnableInvaderEnemy": True,
    "bEnableFastTravel": True,
    "bEnableNonLoginPenalty": False,
    "bExistPlayerAfterLogout": False,
    "bIsUseBackupSaveData": True,
    "bAutoResetGuildNoOnlinePlayers": False,
    "AutoResetGuildTimeNoOnlinePlayers": 72.0,
    "bCanPickupOtherGuildDeathPenaltyDrop": False,
    "bEnableDefenseOtherGuildPlayer": False,
    "DeathPenalty": "All",
    "PalSpawnNumRate": 1.0,
}


def _playtime_windows(player, now, since_30d, since_365d):
    total_30d = 0
    total_365d = 0
    online = False
    open_seconds = 0
    for session in player.sessions.all():
        ended_at, active = _session_end(session, now)
        duration = _duration_seconds(session.started_at, ended_at)
        total_30d += _duration_seconds(max(session.started_at, since_30d), ended_at)
        total_365d += _duration_seconds(max(session.started_at, since_365d), ended_at)
        online = online or active
        if session.ended_at is None:
            open_seconds += duration
    total_all = player.minutes_lifetime * 60 + open_seconds
    return {
        "minutes_30d": total_30d // 60,
        "minutes_365d": total_365d // 60,
        "minutes_all": total_all // 60,
        "online": online,
    }


def _compute_leaderboard():
    now = timezone.now()
    since_30d = now - timedelta(days=30)
    since_365d = now - timedelta(days=365)
    session_window = now - timedelta(days=settings.SESSION_RETENTION_DAYS)
    queryset = Player.objects.prefetch_related(
        Prefetch(
            "sessions",
            queryset=PlayerSession.objects.filter(started_at__gte=session_window).order_by("-started_at"),
        )
    )
    entries = []
    for player in queryset:
        windows = _playtime_windows(player, now, since_30d, since_365d)
        entries.append({
            "id": player.public_id,
            "name": player.name,
            "account_name": player.account_name,
            "level": player.level,
            "first_seen": _iso(player.first_seen),
            "last_seen": _iso(player.last_seen),
            "online": windows["online"],
            "minutes_30d": windows["minutes_30d"],
            "minutes_365d": windows["minutes_365d"],
            "minutes_all": windows["minutes_all"],
        })

    def ranked(key):
        return sorted(entries, key=lambda e: (e[key], e["level"], e["name"].casefold()), reverse=True)[:LEADERBOARD_LIMIT]

    by_level = sorted(entries, key=lambda e: (e["level"], e["minutes_365d"], e["name"].casefold()), reverse=True)[:LEADERBOARD_LIMIT]
    return {
        "generated_at": _iso(now),
        "windows": {"month_days": 30, "year_days": 365},
        "by_playtime": {
            "30d": ranked("minutes_30d"),
            "365d": ranked("minutes_365d"),
            "all": ranked("minutes_all"),
        },
        "by_level": by_level,
        "total_players": len(entries),
    }


@require_GET
@never_cache
def leaderboard(request):
    response = JsonResponse(_cached_payload("leaderboard:v1", _compute_leaderboard))
    response.headers["Cache-Control"] = "no-store"
    return response


def _session_hour_buckets(started_at, ended_at, now):
    cursor = started_at
    end = ended_at or now
    while cursor < end:
        next_hour = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        chunk_end = min(next_hour, end)
        minutes = (chunk_end - cursor).total_seconds() / 60.0
        yield cursor.weekday(), cursor.hour, minutes
        cursor = chunk_end


def _compute_activity_heatmap(range_name, duration):
    now = timezone.now()
    since = now - duration
    grid = [[0.0 for _ in range(24)] for _ in range(7)]
    hour_totals = [0.0 for _ in range(24)]
    day_totals = [0.0 for _ in range(7)]
    session_count = 0
    queryset = PlayerSession.objects.filter(
        last_seen__gte=since
    ).select_related("player")
    for session in queryset.iterator(chunk_size=500):
        session_count += 1
        for dow, hour, minutes in _session_hour_buckets(session.started_at, session.ended_at, now):
            if minutes <= 0:
                continue
            grid[dow][hour] += minutes
            hour_totals[hour] += minutes
            day_totals[dow] += minutes
    peak_hour = max(range(24), key=lambda h: hour_totals[h]) if any(hour_totals) else None
    peak_day = max(range(7), key=lambda d: day_totals[d]) if any(day_totals) else None
    return {
        "generated_at": _iso(now),
        "range": range_name,
        "weekday_labels": WEEKDAY_LABELS,
        "grid": [[round(v, 1) for v in row] for row in grid],
        "hour_totals": [round(v, 1) for v in hour_totals],
        "day_totals": [round(v, 1) for v in day_totals],
        "peak_hour": peak_hour,
        "peak_day": WEEKDAY_LABELS[peak_day] if peak_day is not None else None,
        "session_count": session_count,
        "total_minutes": round(sum(hour_totals), 1),
    }


@require_GET
@never_cache
def activity_heatmap(request):
    range_name = request.GET.get("range", "30d")
    duration = ACTIVITY_RANGES.get(range_name)
    if not duration:
        return JsonResponse({"error": "unsupported range"}, status=400)
    response = JsonResponse(
        _cached_payload(f"activity_heatmap:{range_name}", lambda: _compute_activity_heatmap(range_name, duration))
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@require_GET
def world_objects(request):
    dataset = LatestDataset.objects.filter(key="game_data").first()
    if not dataset:
        response = JsonResponse({
            "available": False,
            "objects": [],
            "count": 0,
            "source_count": 0,
            "supported_count": 0,
            "source_counts": {},
            "active_counts": {},
            "kind_counts": {},
            "omitted_counts": {},
            "truncated": False,
            "stale": True,
            "updated_at": None,
        })
        response.headers["Cache-Control"] = "no-cache, private"
        return response
    now = timezone.now()
    source_clock = dataset.source_clock
    etag = f'"{source_clock.isoformat()}"'
    if request.headers.get("If-None-Match") == etag:
        response = HttpResponse(status=304)
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "no-cache, private"
        return response
    payload = dataset.payload or {}
    response = JsonResponse({
        "available": True,
        "objects": payload.get("objects", []),
        "count": payload.get("count", 0),
        "source_count": payload.get("source_count", 0),
        "supported_count": payload.get("supported_count", payload.get("count", 0)),
        "source_counts": payload.get("source_counts", {}),
        "active_counts": payload.get("active_counts", {}),
        "kind_counts": payload.get("kind_counts", {}),
        "omitted_counts": payload.get("omitted_counts", {}),
        "truncated": bool(payload.get("truncated", False)),
        "stale": source_clock < now - timedelta(seconds=settings.WORLD_DATA_STALE_SECONDS),
        "updated_at": _iso(source_clock),
    })
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache, private"
    return response


def _uptime_pct(window, now):
    since = now - window
    times = list(
        MetricSample.objects.filter(
            source_clock__gte=since, source_clock__lte=now
        ).order_by("source_clock").values_list("source_clock", flat=True)
    )
    if not times:
        return 0.0, []
    if len(times) == 1:
        return min(100.0, DATA_GAP_THRESHOLD / window.total_seconds() * 100), []
    covered = 0.0
    gaps = []
    for prev, curr in zip(times, times[1:]):
        gap = (curr - prev).total_seconds()
        if gap <= DATA_GAP_THRESHOLD:
            covered += gap
        else:
            gaps.append({"from": _iso(prev), "to": _iso(curr), "seconds": int(gap)})
    pct = min(100.0, covered / window.total_seconds() * 100)
    return pct, gaps[:10]


def _compute_telemetry_stats():
    now = timezone.now()
    since_24h = now - timedelta(hours=24)
    uptime_24h, gaps_24h = _uptime_pct(timedelta(hours=24), now)
    uptime_7d, _ = _uptime_pct(timedelta(days=7), now)
    fps_values = list(
        MetricSample.objects.filter(source_clock__gte=since_24h)
        .values_list("server_fps", flat=True)
    )
    fps_values = [v for v in fps_values if v is not None and v > 0]
    if fps_values:
        mean_fps = sum(fps_values) / len(fps_values)
        variance = sum((v - mean_fps) ** 2 for v in fps_values) / len(fps_values)
        std_fps = variance ** 0.5
        fps_cv = round(std_fps / mean_fps, 3) if mean_fps else None
        fps_min = min(fps_values)
        fps_max = max(fps_values)
    else:
        mean_fps = None
        fps_cv = None
        fps_min = None
        fps_max = None
    aggregates = MetricSample.objects.filter(source_clock__gte=since_24h).aggregate(
        avg_players=Avg("current_players"),
        peak_players=Max("current_players"),
        avg_fps=Avg("server_fps_average"),
    )
    metrics = LatestDataset.objects.filter(key="metrics").first()
    world_days = None
    uptime_seconds = None
    if metrics:
        payload = metrics.payload or {}
        world_days = payload.get("days")
        uptime_seconds = payload.get("uptime")
    return {
        "generated_at": _iso(now),
        "uptime": {
            "pct_24h": round(uptime_24h, 2),
            "pct_7d": round(uptime_7d, 2),
            "gaps_24h": gaps_24h,
            "gap_count_24h": len(gaps_24h),
        },
        "fps": {
            "mean_24h": round(mean_fps, 2) if mean_fps else None,
            "min_24h": round(fps_min, 2) if fps_min else None,
            "max_24h": round(fps_max, 2) if fps_max else None,
            "stability_cv_24h": fps_cv,
            "average_24h": round(aggregates["avg_fps"] or 0, 2),
        },
        "players": {
            "average_24h": round(aggregates["avg_players"] or 0, 2),
            "peak_24h": aggregates["peak_players"] or 0,
        },
        "world": {
            "day": world_days,
            "uptime_seconds": uptime_seconds,
        },
        "data_age_threshold_seconds": DATA_GAP_THRESHOLD,
    }


@require_GET
@never_cache
def telemetry_stats(request):
    response = JsonResponse(_cached_payload("telemetry_stats:v1", _compute_telemetry_stats))
    response.headers["Cache-Control"] = "no-store"
    return response


@require_GET
@never_cache
def world_diff(request):
    def compute():
        settings_payload = LatestDataset.objects.filter(key="settings").first()
        current = (settings_payload.payload or {}) if settings_payload else {}
        diffs = []
        for key, vanilla in VANILLA_DEFAULTS.items():
            if key not in current:
                continue
            value = current[key]
            if value == vanilla:
                continue
            diffs.append({"key": key, "vanilla": vanilla, "current": value})
        return {
            "generated_at": _iso(timezone.now()),
            "diffs": diffs,
            "total": len(diffs),
            "has_settings": bool(current),
        }
    response = JsonResponse(_cached_payload("world_diff:v1", compute))
    response.headers["Cache-Control"] = "no-store"
    return response
