import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from palworld_site.config import read_secret


class SecretConfigurationTests(SimpleTestCase):
    def test_file_value_takes_precedence_over_environment_value(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            path.write_text("from-file\n", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"TEST_SECRET_FILE": str(path), "TEST_SECRET": "from-env"},
                clear=False,
            ):
                self.assertEqual(read_secret("TEST_SECRET_FILE", "TEST_SECRET"), "from-file")

    def test_missing_required_file_fails_without_falling_back(self):
        with (
            mock.patch.dict(
                os.environ,
                {"TEST_SECRET_FILE": "/does/not/exist", "TEST_SECRET": "from-env"},
                clear=False,
            ),
            self.assertRaises(ImproperlyConfigured),
        ):
            read_secret("TEST_SECRET_FILE", "TEST_SECRET")

    def test_optional_empty_value_returns_default(self):
        with mock.patch.dict(
            os.environ,
            {"TEST_SECRET_FILE": "", "TEST_SECRET": ""},
            clear=False,
        ):
            self.assertEqual(read_secret("TEST_SECRET_FILE", "TEST_SECRET", required=False), "")

    def test_placeholder_secret_is_rejected(self):
        with (
            mock.patch.dict(
                os.environ,
                {"TEST_SECRET_FILE": "", "TEST_SECRET": "replace-with-a-real-secret"},
                clear=False,
            ),
            self.assertRaises(ImproperlyConfigured),
        ):
            read_secret("TEST_SECRET_FILE", "TEST_SECRET")

    def _load_settings(self, **values):
        environment = os.environ.copy()
        environment.update(
            {
                "DJANGO_SECRET_KEY": "django-test-secret",
                "PLAYER_HASH_SECRET": "player-test-secret",
                "PUBLIC_SITE_URL": "https://testserver",
                "SITE_ADMIN_USERS": "admin@example.com",
                "PRIVACY_CONTROLLER_NAME": "Test controller",
                "PRIVACY_CONTACT_EMAIL": "privacy@testserver",
                "DJANGO_SETTINGS_MODULE": "palworld_site.settings",
                "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            }
        )
        environment.update(values)
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import palworld_site.settings; print(palworld_site.settings.PALWORLD_API_VERIFY_TLS)",
            ],
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_player_hash_secret_is_required(self):
        result = self._load_settings(PLAYER_HASH_SECRET="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PLAYER_HASH_SECRET", result.stderr)

    def test_player_hash_secret_cannot_equal_django_secret_key(self):
        result = self._load_settings(PLAYER_HASH_SECRET="django-test-secret")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be different", result.stderr)

    def test_malformed_tls_flag_keeps_verification_enabled(self):
        result = self._load_settings(PALWORLD_API_VERIFY_TLS="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True")
