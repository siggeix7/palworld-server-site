from django.urls import path

from . import admin_views, api_views, live_map, views


urlpatterns = [
    path("api/openapi.json", api_views.openapi_schema, name="openapi-schema"),
    path("api/v1/session", api_views.session, name="session-api"),
    path("api/v1/server/access", api_views.server_access, name="server-access-api"),
    path("api/v1/snapshot", views.snapshot, name="snapshot"),
    path("api/v1/history", views.history, name="history"),
    path("api/v1/players", views.players, name="player-archive"),
    path("api/v1/player/<str:public_id>", views.player_detail, name="player-api"),
    path("api/v1/leaderboard", views.leaderboard, name="leaderboard-api"),
    path("api/v1/activity/heatmap", views.activity_heatmap, name="activity-heatmap"),
    path("api/v1/world/objects", views.world_objects, name="world-objects"),
    path("api/v1/live-map/config", live_map.config, name="live-map-config"),
    path(
        "api/v1/live-map/catalogue",
        live_map.catalogue,
        name="live-map-catalogue",
    ),
    path("api/v1/live-map/players", live_map.players, name="live-map-players"),
    path("api/v1/live-map/objects", live_map.objects, name="live-map-objects"),
    path("api/v1/telemetry/stats", views.telemetry_stats, name="telemetry-stats"),
    path("api/v1/world/diff", views.world_diff, name="world-diff"),
    path("api/v1/palworld/players", admin_views.palworld_players, name="palworld-players"),
    path(
        "api/v1/admin/player-ips",
        admin_views.player_ip_addresses,
        name="admin-player-ips",
    ),
    path(
        "api/v1/admin/weekly-report-schedule",
        admin_views.weekly_report_schedule,
        name="admin-weekly-report-schedule",
    ),
    path("api/v1/palworld/info", admin_views.palworld_info, name="palworld-info"),
    path(
        "api/v1/palworld/admin/players",
        admin_views.palworld_admin_players,
        name="palworld-admin-players",
    ),
    path(
        "api/v1/palworld/announce",
        admin_views.palworld_announce,
        name="palworld-announce",
    ),
    path("api/v1/palworld/kick", admin_views.palworld_kick, name="palworld-kick"),
    path("api/v1/palworld/ban", admin_views.palworld_ban, name="palworld-ban"),
    path("api/v1/palworld/unban", admin_views.palworld_unban, name="palworld-unban"),
    path("api/v1/guild/data", admin_views.guild_data, name="guild-data"),
]
