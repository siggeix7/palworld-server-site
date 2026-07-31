from datetime import timedelta
import json
import logging
import re
import secrets

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .accounts import is_site_admin
from .models import GuildSnapshot, LatestDataset

logger = logging.getLogger(__name__)
GUILD_SNAPSHOT_STALE_AFTER = timedelta(minutes=15)
OPAQUE_ID_PATTERN = re.compile(r"[0-9a-f]{20}\Z")
GUILD_FIELDS = {
    "group_id", "guild_name", "players", "base_count", "pal_count",
    "worker_count", "working_count", "problem_worker_count",
    "active_raid_count",
}
BASE_FIELDS = {
    "base_id", "group_id", "name", "location_x", "location_y",
    "worker_count", "working_count", "sick_count", "hungry_count",
    "low_sanity_count", "problem_worker_count", "work_types", "raid_active",
}
COUNT_FIELDS = {
    "base_count", "pal_count", "worker_count", "working_count",
    "problem_worker_count", "active_raid_count", "sick_count", "hungry_count",
    "low_sanity_count",
}
WORLD_FIELDS = {
    "active_raid_count", "oil_rig_count", "oil_rig_alert_count",
    "oil_rig_cleared_count",
}
DIAGNOSTIC_FIELDS = {
    "unowned_base_count", "missing_worker_container_count",
    "unresolved_worker_count",
}
PLAYER_FIELDS = {
    "player_id", "player_name", "guild_id", "is_admin", "level", "exp",
    "owned_pal_count", "unused_status_points", "status_points",
}
PLAYER_STATUS_FIELDS = {
    "max_hp", "stamina", "attack", "carry_weight", "capture_rate",
    "work_speed",
}


def _admin_required(request):
    if not is_site_admin(request.user):
        raise PermissionDenied


def _nonnegative_int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _is_nonnegative_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_guild_payload(payload):
    if not isinstance(payload, dict):
        return "payload must be an object"
    schema_version = payload.get("schema_version")
    if schema_version not in {2, 3}:
        return "unsupported schema_version"
    supported_fields = {
        "schema_version", "guilds", "bases", "world", "diagnostics",
    }
    if schema_version == 3:
        supported_fields.add("players")
    if set(payload) - supported_fields:
        return "payload contains unsupported fields"
    for key in ("guilds", "bases"):
        if not isinstance(payload.get(key), list):
            return f"{key} must be an array"
    if not isinstance(payload.get("world"), dict):
        return "world must be an object"
    if not isinstance(payload.get("diagnostics"), dict):
        return "diagnostics must be an object"
    if schema_version == 3 and not isinstance(payload.get("players"), list):
        return "players must be an array"
    if len(payload["guilds"]) > 256 or len(payload["bases"]) > 512:
        return "payload contains too many guilds or bases"
    if schema_version == 3 and len(payload["players"]) > 4096:
        return "payload contains too many players"

    for guild in payload["guilds"]:
        if not isinstance(guild, dict) or set(guild) - GUILD_FIELDS:
            return "each guild must contain only supported fields"
        if not OPAQUE_ID_PATTERN.fullmatch(guild.get("group_id", "")):
            return "each guild must be an object with a group_id"
        if not isinstance(guild.get("guild_name"), str):
            return "guild_name must be a string"
        if any(
            field in guild and not _is_nonnegative_int(guild[field])
            for field in COUNT_FIELDS
        ):
            return "guild counts must be non-negative integers"
        players = guild.get("players")
        if not isinstance(players, list) or len(players) > 64:
            return "guild players must be an array"
        if any(not isinstance(player, dict) for player in players):
            return "each guild player must be an object"
        if any(
            set(player) - {"player_name", "is_admin"}
            or not isinstance(player.get("player_name"), str)
            or not isinstance(player.get("is_admin"), bool)
            for player in players
        ):
            return "each guild player contains invalid fields"

    for base in payload["bases"]:
        if not isinstance(base, dict) or set(base) - BASE_FIELDS:
            return "each base must contain only supported fields"
        if not OPAQUE_ID_PATTERN.fullmatch(
            base.get("base_id", "")
        ) or not OPAQUE_ID_PATTERN.fullmatch(base.get("group_id", "")):
            return "each base must have a base_id and group_id"
        if not isinstance(base.get("name"), str):
            return "base name must be a string"
        if any(
            not isinstance(base.get(field), (int, float))
            or isinstance(base.get(field), bool)
            for field in ("location_x", "location_y")
        ):
            return "base coordinates must be numeric"
        if any(
            field in base and not _is_nonnegative_int(base[field])
            for field in COUNT_FIELDS
        ):
            return "base counts must be non-negative integers"
        if not isinstance(base.get("raid_active"), bool):
            return "base raid_active must be boolean"
        work_types = base.get("work_types")
        if not isinstance(work_types, list) or len(work_types) > 10:
            return "base work_types must be an array"
        if any(not isinstance(work_type, dict) for work_type in work_types):
            return "each base work type must be an object"
        if any(
            set(work_type) != {"key", "count"}
            or not isinstance(work_type["key"], str)
            or not _is_nonnegative_int(work_type["count"])
            for work_type in work_types
        ):
            return "each base work type contains invalid fields"

    for player in payload.get("players", []):
        if not isinstance(player, dict) or set(player) - PLAYER_FIELDS:
            return "each saved player must contain only supported fields"
        if not OPAQUE_ID_PATTERN.fullmatch(player.get("player_id", "")):
            return "each saved player must have a player_id"
        if (
            not isinstance(player.get("player_name"), str)
            or not player["player_name"]
            or len(player["player_name"]) > 128
        ):
            return "saved player names must be non-empty strings"
        guild_id = player.get("guild_id")
        if not isinstance(guild_id, str) or (
            guild_id and not OPAQUE_ID_PATTERN.fullmatch(guild_id)
        ):
            return "saved player guild_id must be empty or opaque"
        if not isinstance(player.get("is_admin"), bool):
            return "saved player is_admin must be boolean"
        if any(
            not _is_nonnegative_int(player.get(field))
            for field in (
                "level", "exp", "owned_pal_count", "unused_status_points",
            )
        ):
            return "saved player counts must be non-negative integers"
        status_points = player.get("status_points")
        if (
            not isinstance(status_points, dict)
            or set(status_points) - PLAYER_STATUS_FIELDS
            or any(not _is_nonnegative_int(value) for value in status_points.values())
        ):
            return "saved player status points are invalid"

    if set(payload["world"]) - WORLD_FIELDS or any(
        not _is_nonnegative_int(value) for value in payload["world"].values()
    ):
        return "world contains invalid fields"
    if set(payload["diagnostics"]) - DIAGNOSTIC_FIELDS or any(
        not _is_nonnegative_int(value) for value in payload["diagnostics"].values()
    ):
        return "diagnostics contains invalid fields"
    return None


def _guild_alerts(snapshot, now=None):
    now = now or timezone.now()
    if not snapshot:
        return [{
            "level": "danger",
            "title": "Sincronizzazione save assente",
            "detail": "Non è ancora stato ricevuto uno snapshot del mondo.",
        }]

    alerts = []
    age = now - snapshot.updated_at
    if age > GUILD_SNAPSHOT_STALE_AFTER:
        alerts.append({
            "level": "danger",
            "title": "Sincronizzazione save in ritardo",
            "detail": f"L'ultimo snapshot risale a {int(age.total_seconds() // 60)} minuti fa.",
        })

    payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
    guilds = payload.get("guilds", [])
    bases = payload.get("bases", [])
    if not isinstance(guilds, list):
        guilds = []
    if not isinstance(bases, list):
        bases = []
    guild_names = {
        guild.get("group_id"): guild.get("guild_name") or guild.get("group_name")
        for guild in guilds
        if isinstance(guild, dict) and guild.get("group_id")
    }

    for guild in guilds:
        if not isinstance(guild, dict) or guild.get("players"):
            continue
        alerts.append({
            "level": "warning",
            "title": "Gilda senza membri",
            "detail": guild.get("guild_name") or guild.get("group_name") or "Gilda senza nome",
        })

    for base in bases:
        if not isinstance(base, dict):
            continue
        base_name = base.get("name") or "Base senza nome"
        guild_name = guild_names.get(base.get("group_id"), "Gilda non riconosciuta")
        if base.get("group_id") not in guild_names:
            alerts.append({
                "level": "danger",
                "title": "Base senza gilda valida",
                "detail": base_name,
            })
        problem_count = _nonnegative_int(base.get("problem_worker_count"))
        if problem_count:
            alerts.append({
                "level": "warning",
                "title": "Pal in difficoltà",
                "detail": f"{base_name} · {guild_name}: {problem_count} lavoratori da controllare.",
            })
        if base.get("raid_active"):
            alerts.append({
                "level": "danger",
                "title": "Invasione attiva",
                "detail": f"{base_name} · {guild_name}",
            })

    diagnostics = payload.get("diagnostics", {})
    if isinstance(diagnostics, dict):
        invalid_references = sum(
            _nonnegative_int(diagnostics.get(key))
            for key in ("missing_worker_container_count", "unresolved_worker_count")
        )
        if invalid_references:
            alerts.append({
                "level": "warning",
                "title": "Riferimenti save scollegati",
                "detail": f"Rilevati {invalid_references} riferimenti a lavoratori o contenitori non risolti.",
            })
    world = payload.get("world", {})
    world_raid_count = (
        _nonnegative_int(world.get("active_raid_count"))
        if isinstance(world, dict)
        else 0
    )
    matched_raid_count = sum(
        bool(base.get("raid_active"))
        for base in bases
        if isinstance(base, dict)
    )
    if world_raid_count > matched_raid_count:
        alerts.append({
            "level": "danger",
            "title": "Invasione non associata",
            "detail": "Lo snapshot segnala un'invasione che non è collegata a una base valida.",
        })
    oil_rig_alerts = (
        _nonnegative_int(world.get("oil_rig_alert_count"))
        if isinstance(world, dict)
        else 0
    )
    if oil_rig_alerts:
        alerts.append({
            "level": "warning",
            "title": "Allarme piattaforma petrolifera",
            "detail": f"{oil_rig_alerts} piattaforme risultano in allerta nello snapshot.",
        })
    return alerts


@require_GET
@never_cache
@login_required
def admin_panel(request):
    _admin_required(request)
    return render(request, "dashboard/admin_panel.html", {
        "app_version": settings.APP_VERSION,
        "public_site_url": settings.PUBLIC_SITE_URL,
        "site_admin": True,
        "active_nav": "admin",
    })


@require_GET
@never_cache
@login_required
def guild_data_page(request):
    return render(
        request,
        "dashboard/guilds.html",
        {
            "app_version": settings.APP_VERSION,
            "public_site_url": settings.PUBLIC_SITE_URL,
            "site_admin": is_site_admin(request.user),
            "active_nav": "guilds",
        },
    )


@require_GET
@never_cache
@login_required
def palworld_players(request):
    _admin_required(request)
    dataset = LatestDataset.objects.filter(key="players").first()
    if not dataset:
        return JsonResponse({
            "available": False,
            "players": [],
            "generated_at": None,
            "stale": True,
        })
    age = (timezone.now() - dataset.source_clock).total_seconds()
    return JsonResponse({
        "available": True,
        "players": (dataset.payload or {}).get("players", []),
        "generated_at": dataset.source_clock.isoformat(),
        "stale": age > settings.DATA_STALE_SECONDS,
    })


@require_GET
@never_cache
@login_required
def palworld_info(request):
    _admin_required(request)
    dataset = LatestDataset.objects.filter(key="info").first()
    if not dataset:
        return JsonResponse({"available": False, "generated_at": None, "stale": True})
    age = (timezone.now() - dataset.source_clock).total_seconds()
    return JsonResponse({
        "available": True,
        **(dataset.payload or {}),
        "generated_at": dataset.source_clock.isoformat(),
        "stale": age > 35 * 60,
    })


@require_POST
@never_cache
@csrf_exempt
def guild_ingest(request):
    expected = settings.ZABBIX_CONNECTOR_TOKEN
    if not expected:
        return JsonResponse({"error": "connector token is not configured"}, status=503)
    authorization = request.headers.get("Authorization", "")
    provided = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not provided or not secrets.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    ):
        return JsonResponse({"error": "unauthorized"}, status=401)
    if request.content_type.lower() != "application/json":
        return JsonResponse({"error": "Content-Type must be application/json"}, status=415)
    content_length = request.META.get("CONTENT_LENGTH")
    try:
        if content_length and int(content_length) > settings.INGEST_MAX_BYTES:
            return JsonResponse({"error": "request body is too large"}, status=413)
    except ValueError:
        return JsonResponse({"error": "invalid Content-Length"}, status=400)
    if len(request.body) > settings.INGEST_MAX_BYTES:
        return JsonResponse({"error": "request body is too large"}, status=413)
    try:
        body = json.loads(request.body or b"{}")
        validation_error = _validate_guild_payload(body)
        if validation_error:
            return JsonResponse({"error": validation_error}, status=422)
        GuildSnapshot.objects.update_or_create(
            id=1,
            defaults={
                "payload": body,
                "updated_at": timezone.now(),
            },
        )
        return JsonResponse({"ok": True})
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid JSON"}, status=400)


@require_GET
@never_cache
@login_required
def guild_data(request):
    snapshot = GuildSnapshot.objects.first()
    if not snapshot:
        response = {
            "schema_version": 2,
            "guilds": [],
            "bases": [],
            "world": {},
            "updated_at": None,
            "stale": True,
        }
        if is_site_admin(request.user):
            response["alerts"] = _guild_alerts(None)
        return JsonResponse(response)
    payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
    response = {
        "schema_version": payload.get("schema_version", 1),
        "guilds": payload.get("guilds", []),
        "bases": payload.get("bases", []),
        "world": payload.get("world", {}),
        "updated_at": snapshot.updated_at.isoformat(),
        "stale": timezone.now() - snapshot.updated_at > GUILD_SNAPSHOT_STALE_AFTER,
    }
    if is_site_admin(request.user):
        response["alerts"] = _guild_alerts(snapshot)
    return JsonResponse(response)
