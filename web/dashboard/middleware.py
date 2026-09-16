import hashlib
import ipaddress
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.db import OperationalError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import patch_cache_control

from .accounts import get_user_profile, needs_terms_acceptance
from .logging import REQUEST_ID_PATTERN, request_id_context
from .models import AuthThrottle

AUTH_RATE_LIMITS = {
    "/accounts/login/": ("login", 10, timedelta(minutes=15)),
    "/accounts/register/": ("register", 5, timedelta(hours=1)),
    "/accounts/resend-verification/": ("resend", 5, timedelta(hours=1)),
    "/accounts/password-reset/": ("password-reset", 5, timedelta(hours=1)),
}
LOGIN_ACCOUNT_RATE_LIMIT = ("login-account", 5, timedelta(minutes=15))


def _request_source(request):
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    remote_address = request.META.get("REMOTE_ADDR", "unknown")
    address = remote_address
    if remote_address in settings.AUTH_TRUSTED_PROXY_ADDRESSES and forwarded_for:
        address = forwarded_for.rsplit(",", 1)[-1].strip() or remote_address
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return address[:128] or "unknown"
    if parsed.version == 6:
        return str(ipaddress.ip_network(f"{parsed}/64", strict=False))
    return str(parsed)


def _login_identifier(request):
    return request.POST.get("username", "").strip().casefold()[:254]


def _consume_auth_attempt(scope, identity, limit, window):
    key = hashlib.sha256(f"{settings.SECRET_KEY}:{scope}:{identity}".encode()).hexdigest()
    now = timezone.now()
    cutoff = now - window
    try:
        if secrets.randbelow(100) == 0:
            AuthThrottle.objects.filter(window_started_at__lt=now - timedelta(days=1)).delete()
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
    access_exempt_prefixes = ("/static/", "/accounts/verify/", "/accounts/reset/")
    access_exempt_paths = (
        "/healthz/",
        "/termini/",
        "/privacy/",
        "/cookie/",
        "/rimborsi/",
        "/accounts/login/",
        "/accounts/logout/",
        "/accounts/register/",
        "/accounts/register/done/",
        "/accounts/resend-verification/",
        "/accounts/password-reset/",
        "/accounts/password-reset/done/",
        "/accounts/pending/",
        "/accounts/password-change/",
        "/accounts/accept-terms/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.SITE_AUTH_REQUIRED:
            return self.get_response(request)

        if request.path in self.access_exempt_paths or request.path.startswith(
            self.access_exempt_prefixes
        ):
            return self.get_response(request)
        if not request.user.is_authenticated:
            if request.path.startswith("/api/"):
                response = JsonResponse({"error": "authentication required"}, status=401)
                patch_cache_control(response, no_store=True, private=True)
                return response
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('login')}?{query}")
        profile = get_user_profile(request.user)
        if not profile.email_verified or not profile.approved:
            if request.path.startswith("/api/"):
                response = JsonResponse({"error": "account approval required"}, status=403)
                patch_cache_control(response, no_store=True, private=True)
                return response
            return redirect("pending-approval")
        if profile.must_change_password:
            if request.path.startswith("/api/"):
                response = JsonResponse({"error": "password change required"}, status=403)
                patch_cache_control(response, no_store=True, private=True)
                return response
            return redirect("password_change")
        if needs_terms_acceptance(profile):
            if request.path.startswith("/api/"):
                response = JsonResponse({"error": "terms acceptance required"}, status=403)
                patch_cache_control(response, no_store=True, private=True)
                return response
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('accept-terms')}?{query}")
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        del view_func, view_args, view_kwargs
        if not settings.SITE_AUTH_REQUIRED:
            return None
        rate_limit = AUTH_RATE_LIMITS.get(request.path)
        if request.method == "POST" and rate_limit:
            scope, limit, window = rate_limit
            buckets = [(scope, _request_source(request), limit, window)]
            if request.path == "/accounts/login/":
                account = _login_identifier(request)
                if account:
                    buckets.append(
                        (*LOGIN_ACCOUNT_RATE_LIMIT[:1], account, *LOGIN_ACCOUNT_RATE_LIMIT[1:])
                    )
            for bucket_scope, identity, bucket_limit, bucket_window in buckets:
                allowed, retry_after = _consume_auth_attempt(
                    bucket_scope, identity, bucket_limit, bucket_window
                )
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


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        requested_id = request.headers.get("X-Request-ID", "")
        request_id = (
            requested_id if REQUEST_ID_PATTERN.fullmatch(requested_id) else uuid.uuid4().hex
        )
        token = request_id_context.set(request_id)
        request.request_id = request_id
        try:
            response = self.get_response(request)
        finally:
            request_id_context.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


class PublicSecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "style-src-attr 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; font-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        return response
