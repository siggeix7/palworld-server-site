from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.views import defaults
from django.views.csrf import csrf_failure as django_csrf_failure
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .accounts import is_site_admin


OPENAPI_PATH = Path(__file__).resolve().parent / "api" / "openapi.json"


@require_GET
@never_cache
def session(request):
    authenticated = request.user.is_authenticated
    site_admin = is_site_admin(request.user)
    routes = {
        "terms": reverse("terms"),
        "profile": reverse("change-username"),
        "password": reverse("password_change"),
        "members": reverse("members") if site_admin else None,
        "admin": reverse("admin-panel") if site_admin else None,
    }
    return JsonResponse(
        {
            "authenticated": authenticated,
            "user": (
                {"username": request.user.username, "email": request.user.email}
                if authenticated
                else None
            ),
            "siteAdmin": site_admin,
            "appVersion": settings.APP_VERSION,
            "routes": routes,
        }
    )


@require_GET
@never_cache
def server_access(request):
    host = settings.PALWORLD_PUBLIC_HOST
    port = settings.PALWORLD_PUBLIC_PORT
    password = settings.PALWORLD_PUBLIC_PASSWORD
    configured = bool(host and port and password)
    response = JsonResponse(
        {
            "host": host,
            "port": port,
            "password": password,
            "address": f"{host}:{port}" if host and port else "",
            "configured": configured,
        }
    )
    response.headers["Cache-Control"] = "no-store, private"
    return response


@require_GET
@never_cache
def openapi_schema(request):
    return HttpResponse(OPENAPI_PATH.read_bytes(), content_type="application/json")


def permission_denied(request, exception=None):
    if request.path.startswith("/api/"):
        response = JsonResponse({"error": "permission denied"}, status=403)
        response.headers["Cache-Control"] = "no-store, private"
        return response
    return defaults.permission_denied(request, exception)


def csrf_failure(request, reason=""):
    if request.path.startswith("/api/"):
        response = JsonResponse({"error": "CSRF verification failed"}, status=403)
        response.headers["Cache-Control"] = "no-store, private"
        return response
    return django_csrf_failure(request, reason=reason)
