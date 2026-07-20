import logging

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordResetForm,
    UserCreationForm,
)

from .emails import get_public_site_parts


logger = logging.getLogger(__name__)


class SiteAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Username o email", max_length=254)


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email")

    def clean_username(self):
        username = self.cleaned_data["username"]
        if "@" in username:
            raise forms.ValidationError("Lo username non può contenere il carattere @.")
        if not username.isascii():
            raise forms.ValidationError("Lo username può contenere soltanto caratteri ASCII.")
        reserved_usernames = {
            identifier
            for identifier in settings.SITE_ADMIN_USERS
            if "@" not in identifier
        }
        if username.casefold() in reserved_usernames:
            raise forms.ValidationError("Questo username è riservato.")
        users = get_user_model().objects
        if users.filter(username__iexact=username).exists():
            raise forms.ValidationError("Esiste già un account con questo username.")
        if users.filter(email__iexact=username).exists():
            raise forms.ValidationError("Questo username non è disponibile.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if not email.isascii():
            raise forms.ValidationError("L'indirizzo email deve usare caratteri ASCII.")
        users = get_user_model().objects
        if users.filter(email__iexact=email).exists():
            raise forms.ValidationError("Esiste già un account con questa email.")
        if users.filter(username__iexact=email).exists():
            raise forms.ValidationError("Questa email non è disponibile.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class ResendVerificationForm(forms.Form):
    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )


class CanonicalPasswordResetForm(PasswordResetForm):
    def save(self, *args, **kwargs):
        try:
            public_site = get_public_site_parts()
        except ValueError as exc:
            logger.error("Password reset email not sent: %s", exc)
            return None
        kwargs["domain_override"] = public_site.netloc
        kwargs["use_https"] = public_site.scheme == "https"
        kwargs["from_email"] = kwargs.get("from_email") or settings.DEFAULT_FROM_EMAIL
        return super().save(*args, **kwargs)
