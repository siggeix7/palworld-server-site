import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

MAX_SECRET_LENGTH = 16 * 1024
PLACEHOLDER_PREFIX = "replace-with-"


def read_secret(file_variable, value_variable, *, required=True, default=""):
    """Read a secret from a mounted file before falling back to an env value."""
    secret_path = os.getenv(file_variable, "").strip()
    if secret_path:
        try:
            with Path(secret_path).open(encoding="utf-8") as secret_file:
                value = secret_file.read(MAX_SECRET_LENGTH + 1).strip()
        except (OSError, UnicodeError) as exc:
            raise ImproperlyConfigured(
                f"Unable to read secret file configured by {file_variable}"
            ) from exc
        if len(value) > MAX_SECRET_LENGTH:
            raise ImproperlyConfigured(f"Secret file configured by {file_variable} is too large")
    else:
        value = os.getenv(value_variable, "").strip()
        if len(value) > MAX_SECRET_LENGTH:
            raise ImproperlyConfigured(f"{value_variable} is too large")

    if not value:
        if required:
            raise ImproperlyConfigured(f"{file_variable} or {value_variable} must be configured")
        return default
    if value.casefold().startswith(PLACEHOLDER_PREFIX):
        raise ImproperlyConfigured(
            f"{file_variable} or {value_variable} still contains a placeholder"
        )
    return value
