import secrets
from datetime import datetime

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import RuntimeState


def _authorized(request):
    authorization = request.headers.get("Authorization", "")
    provided = authorization[7:] if authorization.startswith("Bearer ") else ""
    expected = settings.PRIVATE_API_TOKEN
    return bool(provided and expected) and secrets.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    )


def _collector_state():
    row = RuntimeState.objects.filter(key="collector-status").first()
    return row.value if row and isinstance(row.value, dict) else {}


@require_GET
@never_cache
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    state = _collector_state()
    try:
        heartbeat = datetime.fromisoformat(state.get("heartbeat", ""))
        age = (timezone.now() - heartbeat).total_seconds()
    except (TypeError, ValueError):
        age = None
    healthy = state.get("state") == "running" and age is not None and age <= 60
    return JsonResponse(
        {
            "status": "ok" if healthy else "starting",
            "collector": state.get("state", "unavailable"),
            "version": settings.APP_VERSION,
        },
        status=200 if healthy else 503,
    )


@require_GET
@never_cache
def status(request):
    if not _authorized(request):
        return JsonResponse({"error": "unauthorized"}, status=401)
    state = _collector_state()
    return JsonResponse({
        "state": state.get("state", "unavailable"),
        "started_at": state.get("started_at"),
        "heartbeat": state.get("heartbeat"),
        "datasets": state.get("datasets", {}),
    })
