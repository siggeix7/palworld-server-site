from datetime import timedelta
import hashlib
import hmac
import json
import logging
import re
import secrets
from urllib.parse import urljoin, urlsplit

import requests
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
from .models import GuildSnapshot, LatestDataset, Player, PlayerSession

logger = logging.getLogger(__name__)
GUILD_SNAPSHOT_STALE_AFTER = timedelta(minutes=15)
OPAQUE_ID_PATTERN = re.compile(r"[0-9a-f]{20}\Z")

ADMIN_USERID_MAX_LENGTH = 64
ADMIN_USERID_PATTERN = re.compile(r"^[A-Za-z0-9_:.\-]{1,64}\Z")
ADMIN_ANNOUNCE_MAX_LENGTH = 500
ADMIN_COMMAND_TIMEOUT = 10
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
def player_ip_addresses(request):
    _admin_required(request)
    active_player_ids = set(
        PlayerSession.objects.filter(ended_at__isnull=True).values_list(
            "player_id", flat=True
        )
    )
    players = Player.objects.filter(ip_address__isnull=False).order_by(
        "-ip_observed_at", "name", "public_id"
    )
    return JsonResponse({
        "players": [
            {
                "name": player.name,
                "account_name": player.account_name,
                "ip": player.ip_address,
                "observed_at": (
                    player.ip_observed_at.isoformat()
                    if player.ip_observed_at else None
                ),
                "last_seen": player.last_seen.isoformat(),
                "online": player.id in active_player_ids,
            }
            for player in players
        ],
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


class PalworldCommandError(Exception):
    """Raised when the Palworld REST API rejects a server command."""


class PalworldCommandClient:
    """Minimal synchronous client for admin server commands (announce/kick/ban/unban).

    Unlike the collector's PalworldClient, this one is built per request and
    does not stream or bound wall-clock time: admin actions are rare, return
    small payloads, and rely on the per-phase connect/read timeouts below.
    """

    def __init__(self):
        if not settings.PALWORLD_API_URL:
            raise PalworldCommandError("PALWORLD_API_URL is not configured")
        if not settings.PALWORLD_API_PASSWORD:
            raise PalworldCommandError("PALWORLD_API_PASSWORD is not configured")
        self.base_url = settings.PALWORLD_API_URL.rstrip("/") + "/"
        parsed = urlsplit(self.base_url)
        if parsed.scheme == "http" and not settings.PALWORLD_API_ALLOW_INSECURE_HTTP:
            raise PalworldCommandError("insecure Palworld HTTP API is disabled")
        self.session = requests.Session()
        self.session.auth = (
            settings.PALWORLD_API_USER,
            settings.PALWORLD_API_PASSWORD,
        )
        self.session.trust_env = False
        self.session.headers.update({"Accept": "application/json"})

    def _request(self, method, path, json_body=None):
        url = urljoin(self.base_url, path.lstrip("/"))
        try:
            response = self.session.request(
                method,
                url,
                json=json_body,
                timeout=(settings.PALWORLD_API_CONNECT_TIMEOUT, ADMIN_COMMAND_TIMEOUT),
                verify=settings.PALWORLD_API_VERIFY_TLS,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise PalworldCommandError(f"Palworld unreachable: {exc}") from exc
        if response.status_code in {401, 403}:
            raise PalworldCommandError("Palworld authentication failed")
        if response.status_code == 404:
            raise PalworldCommandError("Palworld endpoint not found")
        if response.status_code == 400:
            detail = (response.text or "")[:200]
            raise PalworldCommandError(f"Palworld rejected the request: {detail}")
        if not response.ok:
            raise PalworldCommandError(f"Palworld HTTP {response.status_code}")
        try:
            return response.json() if response.content else {}
        except ValueError as exc:
            raise PalworldCommandError("Palworld returned an invalid response") from exc

    def players(self):
        data = self._request("GET", "v1/api/players")
        return data.get("players", []) if isinstance(data, dict) else []

    def announce(self, message):
        return self._request("POST", "v1/api/announce", {"message": message})

    def kick(self, userid):
        return self._request("POST", "v1/api/kick", {"userid": userid})

    def ban(self, userid):
        return self._request("POST", "v1/api/ban", {"userid": userid})

    def unban(self, userid):
        return self._request("POST", "v1/api/unban", {"userid": userid})

    def close(self):
        self.session.close()


def _palworld_command(method, *args):
    client = PalworldCommandClient()
    try:
        return getattr(client, method)(*args)
    finally:
        client.close()


def _clean_command_user(value):
    return "" if value is None else str(value).strip()


def _valid_command_user(userid):
    return bool(userid) and bool(ADMIN_USERID_PATTERN.fullmatch(userid))


def _command_number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _command_audit_id(userid):
    return hmac.new(
        settings.PLAYER_HASH_SECRET.encode("utf-8"),
        f"admin-command:{userid}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]


@require_GET
@never_cache
@login_required
def palworld_admin_players(request):
    _admin_required(request)
    try:
        players = _palworld_command("players")
    except PalworldCommandError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    minimal = []
    for raw in players:
        if not isinstance(raw, dict):
            continue
        userid = _clean_command_user(
            raw.get("userId")
            or raw.get("user_id")
            or raw.get("playerId")
            or raw.get("player_id")
        )
        if not _valid_command_user(userid):
            continue
        minimal.append({
            "userId": userid,
            "name": str(raw.get("name") or raw.get("nickname") or "").strip()[:128],
            "level": _nonnegative_int(raw.get("level")),
            "ping": round(_command_number(raw.get("ping")), 1),
            "location_x": _command_number(raw.get("location_x") or raw.get("locationX")),
            "location_y": _command_number(raw.get("location_y") or raw.get("locationY")),
        })
    return JsonResponse({"players": minimal})


@require_POST
@never_cache
@login_required
def palworld_announce(request):
    _admin_required(request)
    if request.content_type != "application/json":
        return JsonResponse({"error": "Content-Type must be application/json"}, status=415)
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return JsonResponse({"error": "JSON body must be an object"}, status=400)
    message = body.get("message")
    if not isinstance(message, str):
        return JsonResponse({"error": "message must be a string"}, status=400)
    message = message.strip()
    if not message:
        return JsonResponse({"error": "message required"}, status=400)
    if len(message) > ADMIN_ANNOUNCE_MAX_LENGTH:
        return JsonResponse(
            {"error": f"message exceeds {ADMIN_ANNOUNCE_MAX_LENGTH} characters"},
            status=400,
        )
    if any(not char.isprintable() for char in message):
        return JsonResponse({"error": "message contains control characters"}, status=400)
    try:
        _palworld_command("announce", message)
    except PalworldCommandError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    logger.info("Admin %s sent a %d-character announcement", request.user.username, len(message))
    return JsonResponse({"ok": True})


def _command_target_from_body(request):
    if request.content_type != "application/json":
        return None, JsonResponse(
            {"error": "Content-Type must be application/json"}, status=415
        )
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"error": "invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return None, JsonResponse({"error": "JSON body must be an object"}, status=400)
    raw_userid = body.get("userid")
    if not isinstance(raw_userid, str):
        return None, JsonResponse({"error": "userid must be a string"}, status=400)
    userid = _clean_command_user(raw_userid)
    if not _valid_command_user(userid):
        return None, JsonResponse(
            {"error": "userid required (alphanumeric, max 64 chars)"},
            status=400,
        )
    return userid, None


@require_POST
@never_cache
@login_required
def palworld_kick(request):
    _admin_required(request)
    userid, error = _command_target_from_body(request)
    if error is not None:
        return error
    try:
        _palworld_command("kick", userid)
    except PalworldCommandError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    logger.info("Admin %s kicked target=%s", request.user.username, _command_audit_id(userid))
    return JsonResponse({"ok": True})


@require_POST
@never_cache
@login_required
def palworld_ban(request):
    _admin_required(request)
    userid, error = _command_target_from_body(request)
    if error is not None:
        return error
    try:
        _palworld_command("ban", userid)
    except PalworldCommandError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    logger.info("Admin %s banned target=%s", request.user.username, _command_audit_id(userid))
    return JsonResponse({"ok": True})


@require_POST
@never_cache
@login_required
def palworld_unban(request):
    _admin_required(request)
    userid, error = _command_target_from_body(request)
    if error is not None:
        return error
    try:
        _palworld_command("unban", userid)
    except PalworldCommandError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    logger.info("Admin %s unbanned target=%s", request.user.username, _command_audit_id(userid))
    return JsonResponse({"ok": True})


@require_POST
@never_cache
@csrf_exempt
def guild_ingest(request):
    expected = settings.PRIVATE_API_TOKEN
    if not expected:
        return JsonResponse({"error": "private API token is not configured"}, status=503)
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
        if content_length and int(content_length) > settings.PRIVATE_API_MAX_BYTES:
            return JsonResponse({"error": "request body is too large"}, status=413)
    except ValueError:
        return JsonResponse({"error": "invalid Content-Length"}, status=400)
    if len(request.body) > settings.PRIVATE_API_MAX_BYTES:
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
