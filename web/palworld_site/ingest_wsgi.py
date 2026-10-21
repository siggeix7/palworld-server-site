import os

from django.core.wsgi import get_wsgi_application

from .telemetry import configure

os.environ["DJANGO_SETTINGS_MODULE"] = "palworld_site.ingest_settings"
configure("ingest", django=True)
application = get_wsgi_application()
