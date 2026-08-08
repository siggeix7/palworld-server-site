import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
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


def _email_context(**extra):
    context = {"public_site_url": settings.PUBLIC_SITE_URL}
    context.update(extra)
    return context


def _send_html_email(subject, text_template, html_template, context, recipients, **kwargs):
    text_message = render_to_string(text_template, context)
    html_message = render_to_string(html_template, context)
    message = EmailMultiAlternatives(
        subject,
        text_message,
        kwargs.get("from_email", settings.DEFAULT_FROM_EMAIL),
        recipients,
    )
    message.attach_alternative(html_message, "text/html")
    return message.send(fail_silently=kwargs.get("fail_silently", False))


def send_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)
    verify_url = _absolute_url(
        request, reverse("verify-email", kwargs={"uidb64": uid, "token": token})
    )
    context = _email_context(user=user, verify_url=verify_url)
    _send_html_email(
        "Conferma la registrazione a Palworld Server Observatory",
        "dashboard/emails/verify_email.txt",
        "dashboard/emails/verify_email.html",
        context,
        [user.email],
    )


def send_approval_email(request, user):
    try:
        login_url = _absolute_url(request, reverse("login"))
    except ValueError as exc:
        logger.error("Approval email not sent: %s", exc)
        return
    context = _email_context(user=user, login_url=login_url)
    _send_html_email(
        "Il tuo account Palworld Server Observatory è stato abilitato",
        "dashboard/emails/account_approved.txt",
        "dashboard/emails/account_approved.html",
        context,
        [user.email],
        fail_silently=True,
    )


def admin_email_recipients():
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
    return sorted(recipients)


def send_weekly_player_email(user, context):
    return _send_html_email(
        f"Il tuo report settimanale Palworld · {context['since_label']} → {context['until_label']}",
        "dashboard/emails/weekly_report.txt",
        "dashboard/emails/weekly_report.html",
        context,
        [user.email],
    )


def notify_admins_of_pending_user(request, user):
    recipients = admin_email_recipients()
    if not recipients:
        return 0
    try:
        members_url = _absolute_url(request, reverse("members"))
    except ValueError as exc:
        logger.error("Pending member notification not sent: %s", exc)
        return 0
    context = _email_context(user=user, members_url=members_url)
    return _send_html_email(
        "Nuovo membro in attesa di approvazione",
        "dashboard/emails/admin_new_member.txt",
        "dashboard/emails/admin_new_member.html",
        context,
        sorted(recipients),
    )
