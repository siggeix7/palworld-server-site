from django.contrib.auth import views as auth_views
from django.urls import path

from dashboard import account_views, admin_views, live_map, views
from dashboard.forms import CanonicalPasswordResetForm, SiteAuthenticationForm


urlpatterns = [
    path(
        "accounts/login/",
        account_views.SiteLoginView.as_view(authentication_form=SiteAuthenticationForm),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "accounts/password-change/",
        account_views.SitePasswordChangeView.as_view(),
        name="password_change",
    ),
    path("accounts/register/", account_views.register, name="register"),
    path(
        "accounts/register/done/",
        account_views.registration_done,
        name="registration-done",
    ),
    path(
        "accounts/verify/<uidb64>/<token>/",
        account_views.verify_email,
        name="verify-email",
    ),
    path(
        "accounts/resend-verification/",
        account_views.resend_verification,
        name="resend-verification",
    ),
    path("accounts/pending/", account_views.pending_approval, name="pending-approval"),
    path(
        "accounts/accept-terms/",
        account_views.accept_terms,
        name="accept-terms",
    ),
    path("accounts/members/", account_views.members, name="members"),
    path(
        "accounts/members/<int:profile_id>/delete/",
        account_views.delete_member,
        name="member-delete",
    ),
    path(
        "accounts/change-username/",
        account_views.change_username,
        name="change-username",
    ),
    path(
        "accounts/password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="dashboard/accounts/password_reset.html",
            form_class=CanonicalPasswordResetForm,
            email_template_name="dashboard/emails/password_reset_email.txt",
            subject_template_name="dashboard/emails/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "accounts/password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="dashboard/accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        account_views.SitePasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="dashboard/accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("", views.home, name="home"),
    path("termini/", views.terms_page, name="terms"),
    path("mappa/", live_map.page, name="map"),
    path("telemetria/", views.telemetry_page, name="telemetry"),
    path("giocatori/", views.players_page, name="players"),
    path("giocatori/<str:public_id>/", views.player_page, name="player"),
    path("accesso/", views.access_page, name="access"),
    path("mondo/", views.world_page, name="world"),
    path("attivita/", views.activity_page, name="activity"),
    path("classifica/", views.leaderboard_page, name="leaderboard"),
    path("orari/", views.peak_hours_page, name="peak-hours"),
    path("gilde/", admin_views.guild_data_page, name="guilds"),
    path("admin-panel/", admin_views.admin_panel, name="admin-panel"),
    path("healthz/", views.health, name="health"),
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
    path("api/v1/admin/player-ips", admin_views.player_ip_addresses, name="admin-player-ips"),
    path("api/v1/palworld/info", admin_views.palworld_info, name="palworld-info"),
    path("api/v1/palworld/admin/players", admin_views.palworld_admin_players, name="palworld-admin-players"),
    path("api/v1/palworld/announce", admin_views.palworld_announce, name="palworld-announce"),
    path("api/v1/palworld/kick", admin_views.palworld_kick, name="palworld-kick"),
    path("api/v1/palworld/ban", admin_views.palworld_ban, name="palworld-ban"),
    path("api/v1/palworld/unban", admin_views.palworld_unban, name="palworld-unban"),
    path("api/v1/guild/data", admin_views.guild_data, name="guild-data"),
]
