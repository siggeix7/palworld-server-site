import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .accounts import is_site_admin
from .models import GuildSnapshot
from .palworld_api import PalworldAPIClient, PalworldAPIError

logger = logging.getLogger(__name__)


def _api_client():
    return PalworldAPIClient()


def _admin_required(request):
    if not is_site_admin(request.user):
        raise PermissionDenied


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
    try:
        client = _api_client()
        players = client.get_players()
        return JsonResponse({"players": players, "generated_at": timezone.now().isoformat()})
    except PalworldAPIError as exc:
        return JsonResponse({"error": str(exc)}, status=502)


@require_GET
@never_cache
@login_required
def palworld_info(request):
    _admin_required(request)
    try:
        return JsonResponse(_api_client().get_info())
    except PalworldAPIError as exc:
        return JsonResponse({"error": str(exc)}, status=502)


@require_POST
@never_cache
@login_required
def palworld_announce(request):
    _admin_required(request)
    import json
    try:
        body = json.loads(request.body or b"{}")
        message = (body.get("message") or "").strip()
        if not message or len(message) > 500:
            return JsonResponse({"error": "message required (max 500 chars)"}, status=400)
        _api_client().announce(message)
        logger.info("Admin %s announced: %s", request.user.username, message[:80])
        return JsonResponse({"ok": True})
    except PalworldAPIError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)


@require_POST
@never_cache
@login_required
def palworld_kick(request):
    _admin_required(request)
    import json
    try:
        body = json.loads(request.body or b"{}")
        uid = (body.get("userid") or "").strip()
        if not uid:
            return JsonResponse({"error": "userid required"}, status=400)
        _api_client().kick(uid)
        logger.info("Admin %s kicked uid=%s", request.user.username, uid)
        return JsonResponse({"ok": True})
    except PalworldAPIError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)


@require_POST
@never_cache
@login_required
def palworld_ban(request):
    _admin_required(request)
    import json
    try:
        body = json.loads(request.body or b"{}")
        uid = (body.get("userid") or "").strip()
        if not uid:
            return JsonResponse({"error": "userid required"}, status=400)
        _api_client().ban(uid)
        logger.info("Admin %s banned uid=%s", request.user.username, uid)
        return JsonResponse({"ok": True})
    except PalworldAPIError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)


@require_POST
@never_cache
@login_required
def palworld_unban(request):
    _admin_required(request)
    import json
    try:
        body = json.loads(request.body or b"{}")
        uid = (body.get("userid") or "").strip()
        if not uid:
            return JsonResponse({"error": "userid required"}, status=400)
        _api_client().unban(uid)
        logger.info("Admin %s unbanned uid=%s", request.user.username, uid)
        return JsonResponse({"ok": True})
    except PalworldAPIError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)


@require_POST
@never_cache
def guild_ingest(request):
    token = settings.ZABBIX_CONNECTOR_TOKEN
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != token:
        return JsonResponse({"error": "unauthorized"}, status=401)
    import json
    try:
        body = json.loads(request.body or b"{}")
        GuildSnapshot.objects.update_or_create(
            id=1,
            defaults={
                "payload": body,
                "updated_at": timezone.now(),
            },
        )
        return JsonResponse({"ok": True})
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)


@require_GET
@never_cache
@login_required
def guild_data(request):
    _admin_required(request)
    snapshot = GuildSnapshot.objects.first()
    if not snapshot:
        return JsonResponse({"guilds": [], "updated_at": None})
    return JsonResponse({
        "guilds": snapshot.payload.get("guilds", []),
        "updated_at": snapshot.updated_at.isoformat(),
    })
