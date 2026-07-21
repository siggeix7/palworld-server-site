import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.urls import reverse_lazy

from .accounts import get_user_profile, has_site_access, is_site_admin
from .emails import (
    notify_admins_of_pending_user,
    send_approval_email,
    send_verification_email,
)
from .forms import RegistrationForm, ResendVerificationForm, UsernameChangeForm
from .models import UserProfile
from .tokens import email_verification_token


logger = logging.getLogger(__name__)


def _notify_admins_if_needed(request, user, profile):
    if (
        not profile.email_verified
        or profile.approved
        or profile.admin_notified_at
    ):
        return
    try:
        sent = notify_admins_of_pending_user(request, user)
    except Exception:
        logger.exception("Unable to notify admins for user_id=%s", user.pk)
        return
    if sent:
        profile.admin_notified_at = timezone.now()
        profile.save(update_fields=["admin_notified_at"])


@method_decorator(login_required, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class SitePasswordChangeView(auth_views.PasswordChangeView):
    template_name = "dashboard/accounts/password_change.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        response = super().form_valid(form)
        profile = get_user_profile(self.request.user)
        if profile.must_change_password:
            profile.must_change_password = False
            profile.save(update_fields=["must_change_password"])
        messages.success(self.request, "Password aggiornata correttamente.")
        return response


class SitePasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "dashboard/accounts/password_reset_confirm.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        profile = UserProfile.objects.filter(user=self.user).first()
        if profile and profile.must_change_password:
            profile.must_change_password = False
            profile.save(update_fields=["must_change_password"])
        return response


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("home" if has_site_access(request.user) else "pending-approval")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = form.save()
        except IntegrityError:
            form.add_error(
                None,
                "Username o email non disponibili. Riprova con valori diversi.",
            )
            return render(request, "dashboard/accounts/register.html", {"form": form})
        get_user_profile(user)
        try:
            send_verification_email(request, user)
            messages.success(request, "Account creato. Controlla la tua email per confermarlo.")
        except Exception:
            logger.exception("Unable to send verification email for user_id=%s", user.pk)
            messages.error(
                request,
                "Account creato, ma l'email non è stata inviata. Riprova dalla pagina di reinvio.",
            )
        return redirect("registration-done")
    return render(request, "dashboard/accounts/register.html", {"form": form})


def registration_done(request):
    return render(request, "dashboard/accounts/registration_done.html")


@require_http_methods(["GET", "POST"])
@never_cache
def verify_email(request, uidb64, token):
    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = get_user_model().objects.get(pk=user_id)
    except (ValueError, TypeError, OverflowError, get_user_model().DoesNotExist):
        user = None
    if (
        not user
        or not user.is_active
        or not email_verification_token.check_token(user, token)
    ):
        return render(request, "dashboard/accounts/verification_invalid.html", status=400)
    if request.method == "GET":
        return render(
            request,
            "dashboard/accounts/verify_email_confirm.html",
            {"verification_user": user},
        )
    profile = get_user_profile(user)
    if not profile.email_verified:
        profile.email_verified = True
        profile.save(update_fields=["email_verified"])
        _notify_admins_if_needed(request, user, profile)
    login(request, user, backend="dashboard.auth_backends.EmailOrUsernameBackend")
    messages.success(request, "Email confermata correttamente.")
    return redirect("home" if has_site_access(user) else "pending-approval")


@require_http_methods(["GET", "POST"])
def resend_verification(request):
    initial = {"email": request.user.email} if request.user.is_authenticated else None
    form = ResendVerificationForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        user = get_user_model().objects.filter(
            email__iexact=form.cleaned_data["email"], is_active=True
        ).first()
        if user and not get_user_profile(user).email_verified:
            try:
                send_verification_email(request, user)
            except Exception:
                logger.exception("Unable to resend verification email for user_id=%s", user.pk)
        messages.success(
            request,
            "Se l'indirizzo è registrato e non ancora verificato, riceverai una nuova email.",
        )
        return redirect("login")
    return render(request, "dashboard/accounts/resend_verification.html", {"form": form})


@login_required
@never_cache
def pending_approval(request):
    profile = get_user_profile(request.user)
    if has_site_access(request.user):
        return redirect("home")
    _notify_admins_if_needed(request, request.user, profile)
    return render(
        request,
        "dashboard/accounts/pending.html",
        {"profile": profile, "site_admin": is_site_admin(request.user)},
    )


@login_required
@require_http_methods(["GET", "POST"])
@never_cache
def members(request):
    if not is_site_admin(request.user) or not has_site_access(request.user):
        raise PermissionDenied
    if request.method == "POST":
        profile = get_object_or_404(
            UserProfile.objects.select_related("user"),
            pk=request.POST.get("profile_id"),
        )
        action = request.POST.get("action")
        if action == "approve":
            if not profile.email_verified:
                messages.error(request, "L'utente deve prima verificare la propria email.")
            else:
                profile.approved = True
                profile.approved_at = timezone.now()
                profile.approved_by = request.user
                profile.save(update_fields=["approved", "approved_at", "approved_by"])
                send_approval_email(request, profile.user)
                messages.success(request, f"{profile.user.username} è stato approvato.")
        elif action == "revoke" and not is_site_admin(profile.user):
            profile.approved = False
            profile.approved_at = None
            profile.approved_by = None
            profile.save(update_fields=["approved", "approved_at", "approved_by"])
            messages.success(request, f"Accesso revocato a {profile.user.username}.")
        return redirect("members")
    profiles = list(UserProfile.objects.select_related("user", "approved_by"))
    for profile in profiles:
        profile.site_admin = is_site_admin(profile.user)
    return render(
        request,
        "dashboard/accounts/members.html",
        {
            "pending_profiles": [profile for profile in profiles if not profile.approved],
            "approved_profiles": [profile for profile in profiles if profile.approved],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@never_cache
def delete_member(request, profile_id):
    if not is_site_admin(request.user) or not has_site_access(request.user):
        raise PermissionDenied
    profile = get_object_or_404(
        UserProfile.objects.select_related("user"),
        pk=profile_id,
    )
    if is_site_admin(profile.user):
        raise PermissionDenied
    if request.method == "POST":
        username = profile.user.username
        profile.user.delete()
        messages.success(request, f"L'account {username} è stato eliminato.")
        return redirect("members")
    return render(
        request,
        "dashboard/accounts/member_confirm_delete.html",
        {"member_profile": profile},
    )


@login_required
@require_http_methods(["GET", "POST"])
@never_cache
def change_username(request):
    if not has_site_access(request.user):
        return redirect("pending-approval")
    profile = get_user_profile(request.user)
    form = UsernameChangeForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        old_username = request.user.username
        new_username = form.cleaned_data["new_username"]
        request.user.username = new_username
        request.user.save(update_fields=["username"])
        logger.info("User %s changed username to %s", old_username, new_username)
        messages.success(
            request,
            f"Nome utente aggiornato da \"{old_username}\" a \"{new_username}\". "
            f"Assicurati che corrisponda al nome usato in Palworld.",
        )
        return redirect("change-username")
    return render(
        request,
        "dashboard/accounts/change_username.html",
        {"form": form, "current_username": request.user.username},
    )
