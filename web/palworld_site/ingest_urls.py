from django.urls import path

from dashboard import ingest_views, views


urlpatterns = [
    path("healthz/", views.health, name="ingest-health"),
    path("api/v1/zabbix/ingest", ingest_views.ingest, name="zabbix-ingest"),
]
