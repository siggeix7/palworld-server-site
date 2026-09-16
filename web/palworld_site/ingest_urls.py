from dashboard import admin_views, collector_views
from django.urls import path

urlpatterns = [
    path("healthz/", collector_views.health, name="private-health"),
    path("api/v1/collector/status", collector_views.status, name="collector-status"),
    path("api/v1/guild/ingest", admin_views.guild_ingest, name="guild-ingest"),
]
