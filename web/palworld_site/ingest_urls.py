from django.urls import path

from dashboard import admin_views, ingest_views, views


urlpatterns = [
    path("healthz/", views.health, name="ingest-health"),
    path("api/v1/zabbix/ingest", ingest_views.ingest, name="zabbix-ingest"),
    path("api/v1/guild/ingest", admin_views.guild_ingest, name="guild-ingest"),
]
