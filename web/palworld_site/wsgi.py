import os

from django.core.wsgi import get_wsgi_application

from .telemetry import configure

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "palworld_site.settings")
configure("web", django=True)
application = get_wsgi_application()
