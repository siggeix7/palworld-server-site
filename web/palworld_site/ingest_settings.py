from .settings import *  # noqa: F403


ROOT_URLCONF = "palworld_site.ingest_urls"
WSGI_APPLICATION = "palworld_site.ingest_wsgi.application"
SECURE_SSL_REDIRECT = False
SITE_AUTH_REQUIRED = False
DATA_UPLOAD_MAX_MEMORY_SIZE = PRIVATE_API_MAX_BYTES  # noqa: F405
MIDDLEWARE = [
    middleware
    for middleware in MIDDLEWARE  # noqa: F405
    if middleware != "whitenoise.middleware.WhiteNoiseMiddleware"
]
