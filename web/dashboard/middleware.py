import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.db import OperationalError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import patch_cache_control

from .accounts import get_user_profile
from .models import AuthThrottle


AUTH_RATE_LIMITS = {
    "/accounts/login/": ("login", 10, timedelta(minutes=15)),
    "/accounts/register/": ("register", 5, timedelta(hours=1)),
    "/accounts/resend-verification/": ("resend", 5, timedelta(hours=1)),
    "/accounts/password-reset/": ("password-reset", 5, timedelta(hours=1)),
}


def _consume_auth_attempt(request, scope, limit, window):
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    remote_address = request.META.get("REMOTE_ADDR", "unknown")
    address = remote_address
    if remote_address in settings.AUTH_TRUSTED_PROXY_ADDRESSES and forwarded_for:
        address = forwarded_for.rsplit(",", 1)[-1].strip() or remote_address
    key = hashlib.sha256(
        f"{settings.SECRET_KEY}:{scope}:{address}".encode()
    ).hexdigest()
    now = timezone.now()
    cutoff = now - window
    try:
        if secrets.randbelow(100) == 0:
            AuthThrottle.objects.filter(
                window_started_at__lt=now - timedelta(days=1)
            ).delete()
        with transaction.atomic():
            throttle, created = AuthThrottle.objects.select_for_update().get_or_create(
                key=key,
                defaults={"window_started_at": now, "attempts": 1},
            )
            if created:
                return True, 0
            if throttle.window_started_at <= cutoff:
                throttle.window_started_at = now
                throttle.attempts = 1
                throttle.save(update_fields=["window_started_at", "attempts"])
                return True, 0
            if throttle.attempts >= limit:
                retry_after = max(
                    1,
                    int((throttle.window_started_at + window - now).total_seconds()),
                )
                return False, retry_after
            throttle.attempts += 1
            throttle.save(update_fields=["attempts"])
        return True, 0
    except OperationalError:
        return False, 60


class SiteAccessMiddleware:
    public_prefixes = ("/accounts/", "/static/")
    public_paths = ("/healthz/", "/api/v1/zabbix/ingest", "/api/v1/guild/ingest")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.SITE_AUTH_REQUIRED:
            return self.get_response(request)

        if request.path in self.public_paths or request.path.startswith(self.public_prefixes):
            return self.get_response(request)
        if not request.user.is_authenticated:
            if request.path.startswith("/api/"):
                return JsonResponse({"error": "authentication required"}, status=401)
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('login')}?{query}")
        profile = get_user_profile(request.user)
        if not profile.email_verified or not profile.approved:
            if request.path.startswith("/api/"):
                return JsonResponse({"error": "account approval required"}, status=403)
            return redirect("pending-approval")
        if profile.must_change_password:
            if request.path.startswith("/api/"):
                return JsonResponse({"error": "password change required"}, status=403)
            return redirect("password_change")
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        del view_func, view_args, view_kwargs
        if not settings.SITE_AUTH_REQUIRED:
            return None
        rate_limit = AUTH_RATE_LIMITS.get(request.path)
        if request.method == "POST" and rate_limit:
            allowed, retry_after = _consume_auth_attempt(request, *rate_limit)
            if not allowed:
                response = render(
                    request,
                    "dashboard/accounts/rate_limited.html",
                    {"retry_after": retry_after},
                    status=429,
                )
                response.headers["Retry-After"] = str(retry_after)
                patch_cache_control(response, no_store=True, private=True)
                return response
        return None


class PublicSecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; font-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        return response
