import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .tokens import email_verification_token


logger = logging.getLogger(__name__)


def get_public_site_parts():
    public_site = urlsplit(settings.PUBLIC_SITE_URL)
    try:
        public_site_port = public_site.port
    except ValueError as exc:
        raise ValueError("PUBLIC_SITE_URL contains an invalid port") from exc
    if (
        public_site.scheme != "https"
        or not public_site.hostname
        or public_site.username
        or public_site.password
        or public_site.query
        or public_site.fragment
        or public_site.path not in {"", "/"}
    ):
        raise ValueError("PUBLIC_SITE_URL must be an absolute HTTPS origin")
    del public_site_port
    return public_site


def _absolute_url(request, path):
    del request
    public_site = get_public_site_parts()
    return f"{public_site.scheme}://{public_site.netloc}{path}"


def send_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    verify_url = _absolute_url(
        request, reverse("verify-email", kwargs={"uidb64": uid, "token": token})
    )
    message = render_to_string(
        "dashboard/emails/verify_email.txt", {"user": user, "verify_url": verify_url}
    )
    send_mail(
        "Conferma la registrazione a Palworld Server Observatory",
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )


def send_approval_email(request, user):
    try:
        login_url = _absolute_url(request, reverse("login"))
    except ValueError as exc:
        logger.error("Approval email not sent: %s", exc)
        return
    message = render_to_string(
        "dashboard/emails/account_approved.txt",
        {"user": user, "login_url": login_url},
    )
    send_mail(
        "Il tuo account Palworld Server Observatory è stato abilitato",
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
    )


def notify_admins_of_pending_user(request, user):
    recipients = {value for value in settings.SITE_ADMIN_USERS if "@" in value}
    usernames = [value for value in settings.SITE_ADMIN_USERS if "@" not in value]
    if usernames:
        username_query = Q()
        for username in usernames:
            username_query |= Q(username__iexact=username)
        recipients.update(
            email
            for email in get_user_model()
            .objects.filter(username_query, is_active=True)
            .values_list("email", flat=True)
            if email
        )
    if not recipients:
        return
    try:
        members_url = _absolute_url(request, reverse("members"))
    except ValueError as exc:
        logger.error("Pending member notification not sent: %s", exc)
        return
    message = render_to_string(
        "dashboard/emails/admin_new_member.txt",
        {"user": user, "members_url": members_url},
    )
    send_mail(
        "Nuovo membro in attesa di approvazione",
        message,
        settings.DEFAULT_FROM_EMAIL,
        sorted(recipients),
        fail_silently=True,
    )
