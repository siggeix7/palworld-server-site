from django.urls import path

from . import spa_views


urlpatterns = [
    path("", spa_views.app, {"page_key": "home"}, name="home"),
    path("mappa/", spa_views.app, {"page_key": "map"}, name="map"),
    path(
        "telemetria/",
        spa_views.app,
        {"page_key": "telemetry"},
        name="telemetry",
    ),
    path("giocatori/", spa_views.app, {"page_key": "players"}, name="players"),
    path("giocatori/<str:public_id>/", spa_views.player_page, name="player"),
    path("accesso/", spa_views.app, {"page_key": "access"}, name="access"),
    path("mondo/", spa_views.app, {"page_key": "world"}, name="world"),
    path("attivita/", spa_views.app, {"page_key": "activity"}, name="activity"),
    path(
        "classifica/",
        spa_views.app,
        {"page_key": "leaderboard"},
        name="leaderboard",
    ),
    path("orari/", spa_views.app, {"page_key": "peak-hours"}, name="peak-hours"),
    path("gilde/", spa_views.guilds_page, name="guilds"),
    path("admin-panel/", spa_views.admin_page, name="admin-panel"),
]
