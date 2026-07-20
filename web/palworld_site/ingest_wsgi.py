import os

from django.core.wsgi import get_wsgi_application


os.environ["DJANGO_SETTINGS_MODULE"] = "palworld_site.ingest_settings"
application = get_wsgi_application()
