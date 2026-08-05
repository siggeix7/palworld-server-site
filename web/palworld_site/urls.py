from django.contrib.auth import views as auth_views
from django.urls import include, path

from dashboard import account_views, views
from dashboard.forms import CanonicalPasswordResetForm, SiteAuthenticationForm


handler403 = "dashboard.api_views.permission_denied"


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
    path("termini/", views.terms_page, name="terms"),
    path("healthz/", views.health, name="health"),
    path("", include("dashboard.spa_urls")),
    path("", include("dashboard.api_urls")),
]
