from django.contrib.auth import views as auth_views
from django.urls import path

from dashboard import account_views, views
from dashboard.forms import CanonicalPasswordResetForm, SiteAuthenticationForm


urlpatterns = [
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="dashboard/accounts/login.html",
            authentication_form=SiteAuthenticationForm,
            redirect_authenticated_user=True,
        ),
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
    path("accounts/members/", account_views.members, name="members"),
    path(
        "accounts/members/<int:profile_id>/delete/",
        account_views.delete_member,
        name="member-delete",
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
    path("vm/", views.vm_dashboard, name="vm-dashboard"),
    path("healthz/", views.health, name="health"),
    path("api/v1/snapshot", views.snapshot, name="snapshot"),
    path("api/v1/history", views.history, name="history"),
    path("api/v1/players", views.players, name="players"),
    path("api/v1/vm/snapshot", views.vm_snapshot, name="vm-snapshot"),
    path("api/v1/vm/history", views.vm_history, name="vm-history"),
    path("api/v1/connector/status", views.connector_status, name="connector-status"),
    path("api/v1/player/<str:public_id>/trail", views.player_trail, name="player-trail"),
]
