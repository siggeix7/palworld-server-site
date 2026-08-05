import json
import threading
import time
from pathlib import Path
from unittest import mock

import requests
from django.conf import settings
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings

from dashboard.collector import CollectorError, PalworldClient, PalworldCollector
from dashboard.models import LatestDataset


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
        self.assertIn("palworld_site.ingest_wsgi:application", entrypoint)
        self.assertIn('SESSION_RETENTION_DAYS: "${SESSION_RETENTION_DAYS:-365}"', compose)
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
