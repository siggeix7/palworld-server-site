from .settings import *  # noqa: F403


ROOT_URLCONF = "palworld_site.ingest_urls"
WSGI_APPLICATION = "palworld_site.ingest_wsgi.application"
MIDDLEWARE = [
    middleware
    for middleware in MIDDLEWARE  # noqa: F405
    if middleware != "whitenoise.middleware.WhiteNoiseMiddleware"
]
