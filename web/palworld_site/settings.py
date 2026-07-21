import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "dashboard.middleware.PublicSecurityHeadersMiddleware",
    "dashboard.middleware.SiteAccessMiddleware",
]

ROOT_URLCONF = "palworld_site.urls"
WSGI_APPLICATION = "palworld_site.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("DATABASE_PATH", str(BASE_DIR / "db.sqlite3")),
        "OPTIONS": {"timeout": 20},
    }
}

LANGUAGE_CODE = "it-it"
TIME_ZONE = os.getenv("TIME_ZONE", "Europe/Rome")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = os.getenv("STATIC_ROOT", str(BASE_DIR.parent / "staticfiles"))
STORAGES = {
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or "test" in sys.argv
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTHENTICATION_BACKENDS = ["dashboard.auth_backends.EmailOrUsernameBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
PASSWORD_RESET_TIMEOUT = int(os.getenv("PASSWORD_RESET_TIMEOUT", "3600"))
APP_VERSION = os.getenv("APP_VERSION", "dev")
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "").rstrip("/")
public_site = urlsplit(PUBLIC_SITE_URL)
try:
    public_site_port = public_site.port
except ValueError as exc:
    raise ImproperlyConfigured("PUBLIC_SITE_URL contains an invalid port") from exc
if (
    public_site.scheme != "https"
    or not public_site.hostname
    or public_site.username
    or public_site.password
    or public_site.query
    or public_site.fragment
    or public_site.path
):
    raise ImproperlyConfigured("PUBLIC_SITE_URL must be an absolute HTTPS origin")
del public_site_port
CSRF_TRUSTED_ORIGINS = [PUBLIC_SITE_URL]
ZABBIX_CONNECTOR_TOKEN = os.getenv("ZABBIX_CONNECTOR_TOKEN", "")
ZABBIX_SOURCE_HOST = os.getenv("ZABBIX_SOURCE_HOST", "").strip()
if not ZABBIX_SOURCE_HOST:
    raise ImproperlyConfigured("ZABBIX_SOURCE_HOST is required")
PLAYER_HASH_SECRET = os.getenv("PLAYER_HASH_SECRET", SECRET_KEY)
INGEST_MAX_BYTES = int(os.getenv("INGEST_MAX_BYTES", "2097152"))
DATA_STALE_SECONDS = int(os.getenv("DATA_STALE_SECONDS", "90"))
POSITION_RETENTION_DAYS = int(os.getenv("POSITION_RETENTION_DAYS", "7"))
METRIC_RETENTION_DAYS = int(os.getenv("METRIC_RETENTION_DAYS", "90"))
CONNECTOR_AUDIT_RETENTION_DAYS = int(
    os.getenv("CONNECTOR_AUDIT_RETENTION_DAYS", "7")
)
VM_DATA_STALE_SECONDS = int(os.getenv("VM_DATA_STALE_SECONDS", "180"))
SITE_AUTH_REQUIRED = True
AUTH_TRUSTED_PROXY_ADDRESSES = {
    value.strip()
    for value in os.getenv("AUTH_TRUSTED_PROXY_ADDRESSES", "127.0.0.1,::1").split(",")
    if value.strip()
}
SITE_ADMIN_USERS = {
    value.strip().casefold()
    for value in os.getenv("SITE_ADMIN_USERS", "").split(",")
    if value.strip()
}
if not SITE_ADMIN_USERS:
    raise ImproperlyConfigured("SITE_ADMIN_USERS must contain at least one identifier")
PALWORLD_PUBLIC_HOST = os.getenv("PALWORLD_PUBLIC_HOST", "").strip()
PALWORLD_PUBLIC_PORT = os.getenv("PALWORLD_PUBLIC_PORT", "8211").strip()
PALWORLD_PUBLIC_PASSWORD = os.getenv("PALWORLD_PUBLIC_PASSWORD", "")
PALWORLD_API_URL = os.getenv("PALWORLD_API_URL", "").strip().rstrip("/")
PALWORLD_API_USER = os.getenv("PALWORLD_API_USER", "admin")
PALWORLD_API_PASSWORD = os.getenv("PALWORLD_API_PASSWORD", "")
PALWORLD_KICK_UNREGISTERED = os.getenv("PALWORLD_KICK_UNREGISTERED", "false").lower() == "true"
PALWORLD_KICK_GRACE_SECONDS = int(os.getenv("PALWORLD_KICK_GRACE_SECONDS", "60"))
PALWORLD_WATCHER_POLL_SECONDS = int(os.getenv("PALWORLD_WATCHER_POLL_SECONDS", "30"))

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.libero.it")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "465"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "guidi.zabbix@libero.it")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "true").lower() == "true"
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "false").lower() == "true"
if EMAIL_USE_SSL and EMAIL_USE_TLS:
    raise ImproperlyConfigured("EMAIL_USE_SSL and EMAIL_USE_TLS cannot both be true")
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "15"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)
SERVER_EMAIL = DEFAULT_FROM_EMAIL

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = os.getenv("DJANGO_USE_X_FORWARDED_HOST", "false").lower() == "true"
SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "false").lower() == "true"
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = os.getenv("DJANGO_SESSION_COOKIE_SECURE", "true").lower() == "true"
CSRF_COOKIE_SECURE = os.getenv("DJANGO_CSRF_COOKIE_SECURE", "true").lower() == "true"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "palworld-public-api",
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}
