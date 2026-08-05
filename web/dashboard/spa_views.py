import re

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET

from .accounts import is_site_admin
from .models import Player


PLAYER_PUBLIC_ID_PATTERN = re.compile(r"^[0-9a-f]{24}\Z")
PAGE_TITLES = {
    "home": "Palworld Server Observatory",
    "map": "Mappa | Palworld Server Observatory",
    "telemetry": "Telemetria | Palworld Server Observatory",
    "players": "Giocatori | Palworld Server Observatory",
    "player": "Profilo giocatore | Palworld Server Observatory",
    "access": "Accesso | Palworld Server Observatory",
    "world": "Mondo | Palworld Server Observatory",
    "activity": "Attività | Palworld Server Observatory",
    "leaderboard": "Classifica | Palworld Server Observatory",
    "peak-hours": "Orari | Palworld Server Observatory",
    "guilds": "Gilde | Palworld Server Observatory",
    "admin": "Admin | Palworld Server Observatory",
}


def _render_app(request, page_key, status=200):
    canonical_url = (
        f"{settings.PUBLIC_SITE_URL}{request.path}"
        if settings.PUBLIC_SITE_URL
        else ""
    )
    return render(
        request,
        "dashboard/app.html",
        {
            "app_version": settings.APP_VERSION,
            "canonical_url": canonical_url,
            "page_title": PAGE_TITLES[page_key],
            "meta_description": "Dashboard riservata del server Palworld",
        },
        status=status,
    )


@require_GET
@never_cache
@ensure_csrf_cookie
def app(request, page_key):
    return _render_app(request, page_key)


@require_GET
@never_cache
@ensure_csrf_cookie
def player_page(request, public_id):
    exists = PLAYER_PUBLIC_ID_PATTERN.fullmatch(public_id) and Player.objects.filter(
        public_id=public_id
    ).exists()
    return _render_app(request, "player", status=200 if exists else 404)


@require_GET
@never_cache
@ensure_csrf_cookie
@login_required
def guilds_page(request):
    return _render_app(request, "guilds")


@require_GET
@never_cache
@ensure_csrf_cookie
@login_required
def admin_page(request):
    if not is_site_admin(request.user):
        raise PermissionDenied
    return _render_app(request, "admin")
