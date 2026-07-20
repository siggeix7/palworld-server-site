import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "development-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "dashboard.middleware.PublicSecurityHeadersMiddleware",
]

ROOT_URLCONF = "palworld_site.urls"
WSGI_APPLICATION = "palworld_site.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
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
APP_VERSION = os.getenv("APP_VERSION", "dev")
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "")
ZABBIX_CONNECTOR_TOKEN = os.getenv("ZABBIX_CONNECTOR_TOKEN", "")
ZABBIX_SOURCE_HOST = os.getenv("ZABBIX_SOURCE_HOST", "").strip()
PLAYER_HASH_SECRET = os.getenv("PLAYER_HASH_SECRET", SECRET_KEY)
INGEST_MAX_BYTES = int(os.getenv("INGEST_MAX_BYTES", "2097152"))
DATA_STALE_SECONDS = int(os.getenv("DATA_STALE_SECONDS", "90"))
POSITION_RETENTION_DAYS = int(os.getenv("POSITION_RETENTION_DAYS", "7"))
METRIC_RETENTION_DAYS = int(os.getenv("METRIC_RETENTION_DAYS", "90"))

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = os.getenv("DJANGO_USE_X_FORWARDED_HOST", "true").lower() == "true"
SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "false").lower() == "true"
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

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
