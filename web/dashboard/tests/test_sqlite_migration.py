import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from dashboard.management.commands.migrate_sqlite_to_postgres import Command
from dashboard.models import PlayerClaimData, WeeklyReportSchedule


class SQLiteMigrationCopyTests(SimpleTestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.source_path = Path(self.temp_directory.name) / "legacy.sqlite3"
        self.addCleanup(self._cleanup_legacy)

    def _cleanup_legacy(self):
        self.temp_directory.cleanup()

    def test_player_copy_accepts_database_created_before_claim_identity_field(self):
        with sqlite3.connect(self.source_path) as source:
            source.executescript(
                """
                CREATE TABLE dashboard_player (
                    id INTEGER PRIMARY KEY,
                    public_id VARCHAR(32) NOT NULL UNIQUE,
                    name VARCHAR(128) NOT NULL,
                    account_name VARCHAR(128) NOT NULL,
                    ip_address VARCHAR(39),
                    ip_observed_at DATETIME,
                    first_seen DATETIME NOT NULL,
                    last_seen DATETIME NOT NULL,
                    level INTEGER NOT NULL,
                    building_count INTEGER NOT NULL,
                    minutes_lifetime INTEGER NOT NULL,
                    session_count_lifetime INTEGER NOT NULL,
                    longest_session_minutes INTEGER NOT NULL
                )
                """
            )
            source.execute(
                """
                INSERT INTO dashboard_player (
                    id, public_id, name, account_name, first_seen, last_seen,
                    level, building_count, minutes_lifetime,
                    session_count_lifetime, longest_session_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    7,
                    "a" * 24,
                    "Legacy Player",
                    "Legacy Account",
                    "2026-09-01 12:00:00",
                    "2026-09-15 12:00:00",
                    12,
                    3,
                    120,
                    4,
                    60,
                ),
            )

        target_path = Path(self.temp_directory.name) / "target.sqlite3"
        root = Path(__file__).resolve().parents[3]
        environment = os.environ.copy()
        environment.update(
            {
                "DATABASE_ENGINE": "sqlite",
                "DATABASE_PATH": str(target_path),
                "DJANGO_SETTINGS_MODULE": "palworld_site.settings",
                "DJANGO_SECRET_KEY": "django-test-key",
                "LEGACY_SQLITE_PATH": str(self.source_path),
                "PLAYER_HASH_SECRET": "player-test-key",
                "PRIVACY_CONTACT_EMAIL": "privacy@testserver",
                "PRIVACY_CONTROLLER_NAME": "test-controller",
                "PUBLIC_SITE_URL": "https://testserver",
                "PYTHONPATH": str(root / "web"),
                "SITE_ADMIN_USERS": "admin@example.com",
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import django
django.setup()
from django.db import connection
from dashboard.management.commands.migrate_sqlite_to_postgres import Command
from dashboard.models import Player

with connection.schema_editor() as editor:
    editor.create_model(Player)
assert Command()._copy_model(Player) == 1
player = Player.objects.get(pk=7)
assert player.name == "Legacy Player"
assert player.claim_public_id is None
""",
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


class MigrationTargetEmptyTests(TestCase):
    def setUp(self):
        self.command = Command()

    def test_migration_default_schedule_is_allowed(self):
        self.command._check_target_empty()

    def test_claim_data_makes_target_non_empty(self):
        PlayerClaimData.objects.create(
            public_id="claim-id",
            payload={},
            snapshot_at=timezone.now(),
        )

        with self.assertRaisesRegex(CommandError, "dashboard.PlayerClaimData"):
            self.command._check_target_empty()

    def test_changed_schedule_makes_target_non_empty(self):
        schedule = WeeklyReportSchedule.objects.get(id=1)
        schedule.enabled = False
        schedule.save()

        with self.assertRaisesRegex(CommandError, "dashboard.WeeklyReportSchedule"):
            self.command._check_target_empty()

    def test_populated_obsolete_table_makes_target_non_empty(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO dashboard_connectorbatch (
                    received_at, record_count, accepted, ignored, rejected,
                    datasets, source_hosts, ignored_items
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [timezone.now(), 1, 1, 0, 0, "[]", "[]", "[]"],
            )

        with self.assertRaisesRegex(CommandError, "dashboard_connectorbatch"):
            self.command._check_target_empty()
