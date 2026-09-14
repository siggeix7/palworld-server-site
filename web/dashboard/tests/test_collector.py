import json
import threading
import time
from datetime import timedelta
from pathlib import Path
from unittest import mock

import requests
from django.conf import settings
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from dashboard.collector import CollectorError, PalworldClient, PalworldCollector
from dashboard.models import (
    AuthThrottle,
    ClaimChallenge,
    ClaimSession,
    ClaimThrottle,
    GuildSnapshot,
    LatestDataset,
    MetricSample,
    Player,
    PlayerClaimData,
    PlayerSession,
    PositionSample,
    RuntimeState,
    ServerEvent,
)
from dashboard.services import cleanup_if_due


class Response:
    def __init__(self, payload, status_code=200):
        self.body = json.dumps(payload).encode("utf-8")
        self.status_code = status_code
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def iter_content(self, chunk_size):
        del chunk_size
        yield self.body


class Session:
    def __init__(self, response):
        self.response = response
        self.auth = None
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response

    def close(self):
        pass


@override_settings(
    PALWORLD_API_URL="http://palworld.example.com:8212",
    PALWORLD_API_USER="admin",
    PALWORLD_API_PASSWORD="secret",
    PALWORLD_API_VERIFY_TLS=False,
    PALWORLD_API_ALLOW_INSECURE_HTTP=True,
)
class PalworldClientTests(SimpleTestCase):
    def test_fetches_json_with_basic_auth_limits_and_no_redirects(self):
        session = Session(Response({"version": "1.0"}))
        client = PalworldClient(session=session)
        self.assertEqual(client.fetch("info"), {"version": "1.0"})
        self.assertEqual(session.auth, ("admin", "secret"))
        url, options = session.calls[0]
        self.assertEqual(url, "http://palworld.example.com:8212/v1/api/info")
        self.assertFalse(options["allow_redirects"])
        self.assertFalse(options["verify"])
        self.assertFalse(session.trust_env)

    def test_rejects_redirects_and_oversized_responses(self):
        client = PalworldClient(session=Session(Response({}, status_code=302)))
        with self.assertRaisesRegex(CollectorError, "http_302"):
            client.fetch("info")

        response = Response({})
        response.body = b"x" * (settings.PALWORLD_API_MAX_BYTES["info"] + 1)
        client = PalworldClient(session=Session(response))
        with self.assertRaisesRegex(CollectorError, "too_large"):
            client.fetch("info")

    def test_enforces_wall_clock_deadline_before_response_headers(self):
        session = Session(Response({}))
        session.get = mock.Mock(side_effect=lambda *_args, **_kwargs: time.sleep(1))
        timeouts = {**settings.PALWORLD_API_TOTAL_TIMEOUTS, "info": 0.05}
        with override_settings(PALWORLD_API_TOTAL_TIMEOUTS=timeouts):
            client = PalworldClient(session=session)
            with self.assertRaisesRegex(CollectorError, "deadline"):
                client.fetch("info")

    def test_normalizes_tls_and_connection_failures(self):
        for error, code in (
            (requests.exceptions.SSLError("certificate failed"), "tls"),
            (requests.ConnectionError("connection refused"), "connection"),
        ):
            with self.subTest(code=code):
                session = Session(Response({}))
                session.get = mock.Mock(side_effect=error)
                client = PalworldClient(session=session)
                with self.assertRaisesRegex(CollectorError, code):
                    client.fetch("info")

    def test_status_checks_the_rest_api_socket(self):
        connection = mock.Mock()
        create_connection = mock.Mock(return_value=connection)
        client = PalworldClient(
            session=Session(Response({})), socket_connection=create_connection
        )
        self.assertTrue(client.fetch("status"))
        create_connection.assert_called_once_with(
            ("palworld.example.com", 8212),
            timeout=settings.PALWORLD_API_CONNECT_TIMEOUT,
        )
        connection.close.assert_called_once()

    @override_settings(PALWORLD_API_PASSWORD="")
    def test_requires_complete_rest_api_configuration(self):
        with self.assertRaisesRegex(CollectorError, "not_configured"):
            PalworldClient(session=Session(Response({})))


class FakeClient:
    def __init__(self, values=None, error=None):
        self.values = values or {}
        self.error = error

    def fetch(self, dataset):
        if self.error:
            raise self.error
        return self.values[dataset]

    def close(self):
        pass


@override_settings(PLAYER_HASH_SECRET="test-player-secret")
class PalworldCollectorTests(TestCase):
    def test_collects_and_persists_sanitized_data(self):
        client = FakeClient({"info": {
            "version": "1.0",
            "servername": "Palworld",
            "description": "Server",
            "worldguid": "must-not-be-stored",
        }})
        collector = PalworldCollector(threading.Event(), client=client)
        self.assertTrue(collector.collect("info"))
        payload = LatestDataset.objects.get(key="info").payload
        self.assertEqual(payload["servername"], "Palworld")
        self.assertNotIn("worldguid", payload)
        self.assertEqual(collector.dataset_state["info"]["failures"], 0)

    def test_failed_status_is_persisted_without_stopping_the_collector(self):
        collector = PalworldCollector(
            threading.Event(),
            client=FakeClient(error=CollectorError("connection")),
        )
        self.assertFalse(collector.collect("status"))
        self.assertFalse(LatestDataset.objects.get(key="status").payload["reachable"])
        self.assertEqual(collector.dataset_state["status"]["error"], "connection")

    def test_database_contention_while_marking_status_offline_is_recoverable(self):
        collector = PalworldCollector(
            threading.Event(),
            client=FakeClient(error=CollectorError("connection")),
        )
        with mock.patch(
            "dashboard.collector.store_dataset",
            side_effect=OperationalError("database is locked"),
        ):
            self.assertFalse(collector.collect("status"))
        self.assertEqual(collector.dataset_state["status"]["error"], "database_busy")

    def test_unexpected_exception_is_contained_and_does_not_stop_the_loop(self):
        collector = PalworldCollector(
            threading.Event(),
            client=FakeClient(error=ValueError("payload surprise")),
        )
        for dataset in ("info", "metrics", "status"):
            with self.subTest(dataset=dataset):
                self.assertFalse(collector.collect(dataset))
                self.assertEqual(
                    collector.dataset_state[dataset]["error"], "unexpected"
                )
                self.assertEqual(collector.dataset_state[dataset]["failures"], 1)


class RetentionTests(TestCase):
    @override_settings(PLAYER_IP_RETENTION_DAYS=30)
    def test_cleanup_removes_expired_player_ips_but_keeps_recent_values(self):
        now = timezone.now()
        old = Player.objects.create(
            public_id="old-player",
            name="Old",
            first_seen=now - timedelta(days=40),
            last_seen=now - timedelta(days=31),
            ip_address="192.0.2.10",
            ip_observed_at=now - timedelta(days=31),
        )
        recent = Player.objects.create(
            public_id="recent-player",
            name="Recent",
            first_seen=now - timedelta(days=2),
            last_seen=now - timedelta(days=1),
            ip_address="192.0.2.11",
            ip_observed_at=now - timedelta(days=29),
        )
        RuntimeState.objects.create(key="retention-cleanup", value={"last": 0})

        cleanup_if_due()

        old.refresh_from_db()
        recent.refresh_from_db()
        self.assertIsNone(old.ip_address)
        self.assertIsNone(old.ip_observed_at)
        self.assertEqual(recent.ip_address, "192.0.2.11")
        self.assertIsNotNone(recent.ip_observed_at)

    @override_settings(
        POSITION_RETENTION_DAYS=7,
        METRIC_RETENTION_DAYS=90,
        SESSION_RETENTION_DAYS=365,
        PLAYER_RETENTION_DAYS=365,
        SAVE_RETENTION_DAYS=30,
        PLAYER_IP_RETENTION_DAYS=30,
    )
    def test_cleanup_prunes_stale_persisted_data_by_its_completion_time(self):
        now = timezone.now()
        expired_player = Player.objects.create(
            public_id="expired-player",
            name="Expired",
            first_seen=now - timedelta(days=400),
            last_seen=now - timedelta(days=366),
        )
        retained_player = Player.objects.create(
            public_id="retained-player",
            name="Retained",
            first_seen=now - timedelta(days=400),
            last_seen=now - timedelta(days=1),
        )
        old_session = PlayerSession.objects.create(
            player=retained_player,
            started_at=now - timedelta(days=400),
            last_seen=now - timedelta(days=366),
            ended_at=now - timedelta(days=366),
        )
        long_session = PlayerSession.objects.create(
            player=retained_player,
            started_at=now - timedelta(days=400),
            last_seen=now - timedelta(days=10),
            ended_at=now - timedelta(days=10),
        )
        active_session = PlayerSession.objects.create(
            player=retained_player,
            started_at=now - timedelta(days=400),
            last_seen=now - timedelta(days=1),
        )
        old_position = PositionSample.objects.create(
            player=retained_player,
            source_clock=now - timedelta(days=8),
            x=1,
            y=1,
        )
        recent_position = PositionSample.objects.create(
            player=retained_player,
            source_clock=now - timedelta(days=6),
            x=2,
            y=2,
        )
        old_metric = MetricSample.objects.create(
            source_clock=now - timedelta(days=91),
        )
        recent_metric = MetricSample.objects.create(
            source_clock=now - timedelta(days=89),
        )
        old_event = ServerEvent.objects.create(
            player=retained_player,
            event_type=ServerEvent.JOIN,
            source_clock=now - timedelta(days=91),
        )
        recent_event = ServerEvent.objects.create(
            player=retained_player,
            event_type=ServerEvent.LEAVE,
            source_clock=now - timedelta(days=89),
        )

        old_datasets = []
        for key in ("game_data", "metrics", "players", "info", "settings", "status"):
            dataset = LatestDataset.objects.create(
                key=key,
                payload={},
                source_clock=now,
            )
            old_datasets.append(dataset)
        LatestDataset.objects.filter(
            pk__in=[dataset.pk for dataset in old_datasets]
        ).update(received_at=now - timedelta(days=366))

        old_save = GuildSnapshot.objects.create(payload={})
        recent_save = GuildSnapshot.objects.create(id=2, payload={})
        GuildSnapshot.objects.filter(pk=old_save.pk).update(
            updated_at=now - timedelta(days=31)
        )
        GuildSnapshot.objects.filter(pk=recent_save.pk).update(
            updated_at=now - timedelta(days=29)
        )
        old_claim_data = PlayerClaimData.objects.create(
            public_id="old-claim",
            payload={},
            snapshot_at=now,
        )
        recent_claim_data = PlayerClaimData.objects.create(
            public_id="recent-claim",
            payload={},
            snapshot_at=now,
        )
        PlayerClaimData.objects.filter(pk=old_claim_data.pk).update(
            updated_at=now - timedelta(days=31)
        )
        PlayerClaimData.objects.filter(pk=recent_claim_data.pk).update(
            updated_at=now - timedelta(days=29)
        )
        expired_challenge = ClaimChallenge.objects.create(
            bearer_hash="a" * 64,
            subject="subject",
            public_player_id="public-player",
            question={},
            correct_answer=0,
            expires_at=now - timedelta(seconds=1),
        )
        expired_claim_session = ClaimSession.objects.create(
            bearer_hash="b" * 64,
            subject="subject",
            public_player_id="public-player",
            idle_expires_at=now + timedelta(days=1),
            absolute_expires_at=now - timedelta(seconds=1),
        )
        expired_throttle = ClaimThrottle.objects.create(
            key="expired",
            window_started_at=now - timedelta(hours=2),
        )
        expired_auth_throttle = AuthThrottle.objects.create(
            key="expired-auth",
            window_started_at=now - timedelta(days=2),
        )
        RuntimeState.objects.create(key="retention-cleanup", value={"last": 0})

        cleanup_if_due()

        self.assertFalse(Player.objects.filter(pk=expired_player.pk).exists())
        self.assertTrue(Player.objects.filter(pk=retained_player.pk).exists())
        self.assertFalse(PlayerSession.objects.filter(pk=old_session.pk).exists())
        self.assertTrue(PlayerSession.objects.filter(pk=long_session.pk).exists())
        self.assertTrue(PlayerSession.objects.filter(pk=active_session.pk).exists())
        self.assertFalse(PositionSample.objects.filter(pk=old_position.pk).exists())
        self.assertTrue(PositionSample.objects.filter(pk=recent_position.pk).exists())
        self.assertFalse(MetricSample.objects.filter(pk=old_metric.pk).exists())
        self.assertTrue(MetricSample.objects.filter(pk=recent_metric.pk).exists())
        self.assertFalse(ServerEvent.objects.filter(pk=old_event.pk).exists())
        self.assertTrue(ServerEvent.objects.filter(pk=recent_event.pk).exists())
        self.assertFalse(
            LatestDataset.objects.filter(
                pk__in=[dataset.pk for dataset in old_datasets]
            ).exists()
        )
        self.assertFalse(GuildSnapshot.objects.filter(pk=old_save.pk).exists())
        self.assertTrue(GuildSnapshot.objects.filter(pk=recent_save.pk).exists())
        self.assertFalse(PlayerClaimData.objects.filter(pk=old_claim_data.pk).exists())
        self.assertTrue(PlayerClaimData.objects.filter(pk=recent_claim_data.pk).exists())
        self.assertFalse(ClaimChallenge.objects.filter(pk=expired_challenge.pk).exists())
        self.assertFalse(
            ClaimSession.objects.filter(pk=expired_claim_session.pk).exists()
        )
        self.assertFalse(ClaimThrottle.objects.filter(pk=expired_throttle.pk).exists())
        self.assertFalse(
            AuthThrottle.objects.filter(pk=expired_auth_throttle.pk).exists()
        )


class DirectArchitectureTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = Path(settings.BASE_DIR).parent

    def read(self, relative_path):
        return (self.root / relative_path).read_text(encoding="utf-8")

    def test_container_runs_collector_and_separate_private_listener(self):
        compose = self.read("docker-compose.yml")
        entrypoint = self.read("docker/entrypoint.sh")
        self.assertIn('PALWORLD_API_URL: "${PALWORLD_API_URL:', compose)
        self.assertIn("${PRIVATE_PORT:-8081}:8001", compose)
        self.assertIn("python3 web/manage.py runcollector", entrypoint)
        self.assertIn("python3 web/manage.py run_retention_cleanup", entrypoint)
        self.assertIn("python3 web/manage.py run_weekly_scheduler", entrypoint)
        self.assertIn("palworld_site.ingest_wsgi:application", entrypoint)
        self.assertIn("postgres:17-bookworm", compose)
        self.assertIn("DATABASE_ENGINE: postgresql", compose)
        self.assertIn('context: "${APP_BUILD_CONTEXT:-.}"', compose)
        self.assertIn(
            'PRIVACY_CONTROLLER_NAME: "${PRIVACY_CONTROLLER_NAME:?PRIVACY_CONTROLLER_NAME is required}"',
            compose,
        )
        self.assertIn(
            'RETENTION_CLEANUP_LOCK_PATH: "${RETENTION_CLEANUP_LOCK_PATH:-/data/palworld-retention-cleanup.lock}"',
            compose,
        )
        self.assertIn('SESSION_RETENTION_DAYS: "${SESSION_RETENTION_DAYS:-365}"', compose)
        self.assertIn('PLAYER_IP_RETENTION_DAYS: "${PLAYER_IP_RETENTION_DAYS:-30}"', compose)
        self.assertIn("--access-logformat", entrypoint)
        self.assertNotIn("%(U)s", entrypoint)

    def test_direct_polling_cadence_and_private_upload_limit(self):
        self.assertEqual(settings.PALWORLD_API_INTERVALS["game_data"], 15)
        self.assertEqual(settings.PALWORLD_API_INTERVALS["players"], 20)
        self.assertEqual(settings.PALWORLD_API_INTERVALS["metrics"], 20)
        self.assertGreaterEqual(settings.PRIVATE_API_MAX_BYTES, 64 * 1024 * 1024)
        private_settings = self.read("web/palworld_site/ingest_settings.py")
        self.assertIn(
            "DATA_UPLOAD_MAX_MEMORY_SIZE = PRIVATE_API_MAX_BYTES",
            private_settings,
        )

    def test_admin_routes_proxy_server_commands_for_admins_only(self):
        root_urls = self.read("web/palworld_site/urls.py")
        api_urls = self.read("web/dashboard/api_urls.py")
        admin_views = self.read("web/dashboard/admin_views.py")
        self.assertIn('include("dashboard.api_urls")', root_urls)
        for path in (
            "palworld/announce",
            "palworld/kick",
            "palworld/ban",
            "palworld/unban",
            "palworld/admin/players",
        ):
            self.assertIn(path, api_urls)
        self.assertIn("PalworldCommandClient", admin_views)
        for view_name in (
            "palworld_announce",
            "palworld_kick",
            "palworld_ban",
            "palworld_unban",
            "palworld_admin_players",
        ):
            self.assertIn(f"def {view_name}(", admin_views)
            self.assertIn(f"_admin_required(request)", admin_views)
