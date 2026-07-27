from django.conf import settings
from django.utils import timezone

from .models import UserProfile


def is_site_admin(user):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    username = user.username.casefold()
    email = user.email.casefold()
    return any(
        identifier == (email if "@" in identifier else username)
        for identifier in settings.SITE_ADMIN_USERS
    )


def get_user_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if is_site_admin(user):
        changed = []
        if not profile.approved:
            profile.approved = True
            profile.approved_at = timezone.now()
            changed.extend(["approved", "approved_at"])
        if changed:
            profile.save(update_fields=changed)
    return profile


def has_site_access(user):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    profile = get_user_profile(user)
    return profile.email_verified and profile.approved


def needs_terms_acceptance(profile):
    return profile.terms_version != settings.CURRENT_TERMS_VERSION


def stamp_terms_acceptance(profile):
    profile.terms_accepted_at = timezone.now()
    profile.terms_version = settings.CURRENT_TERMS_VERSION
    profile.save(update_fields=["terms_accepted_at", "terms_version"])
