import json
import logging
import signal
import socket
import threading
import time
from contextlib import contextmanager
from urllib.parse import urljoin, urlsplit

import requests
from django.conf import settings
from django.db import OperationalError, close_old_connections
from django.utils import timezone

from .models import RuntimeState
from .services import DATASETS, IngestError, run_maintenance, store_dataset


logger = logging.getLogger(__name__)

ENDPOINTS = {
    "info": "v1/api/info",
    "metrics": "v1/api/metrics",
    "players": "v1/api/players",
    "settings": "v1/api/settings",
    "game_data": "v1/api/game-data",
}


class CollectorError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _DeadlineExpired(Exception):
    pass


@contextmanager
def _wall_clock_timeout(seconds):
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame):
        raise _DeadlineExpired

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


class PalworldClient:
    def __init__(self, session=None, socket_connection=None):
        if not (
            settings.PALWORLD_API_URL
            and settings.PALWORLD_API_USER
            and settings.PALWORLD_API_PASSWORD
        ):
            raise CollectorError("not_configured")
        self.base_url = settings.PALWORLD_API_URL.rstrip("/") + "/"
        parsed = urlsplit(self.base_url)
        if parsed.scheme == "http" and not settings.PALWORLD_API_ALLOW_INSECURE_HTTP:
            raise CollectorError("insecure_http_disabled")
        self.host = parsed.hostname
        self.port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self.session = session or requests.Session()
        self.session.auth = (
            settings.PALWORLD_API_USER,
            settings.PALWORLD_API_PASSWORD,
        )
        self.session.trust_env = False
        self.session.headers.update({"Accept": "application/json"})
        self.socket_connection = socket_connection or socket.create_connection

    def fetch(self, dataset):
        if dataset == "status":
            return self._status()
        deadline = time.monotonic() + settings.PALWORLD_API_TOTAL_TIMEOUTS[dataset]
        try:
            with _wall_clock_timeout(settings.PALWORLD_API_TOTAL_TIMEOUTS[dataset]):
                with self.session.get(
                    urljoin(self.base_url, ENDPOINTS[dataset]),
                    timeout=(settings.PALWORLD_API_CONNECT_TIMEOUT, settings.PALWORLD_API_TIMEOUTS[dataset]),
                    verify=settings.PALWORLD_API_VERIFY_TLS,
                    stream=True,
                    allow_redirects=False,
                ) as response:
                    if 300 <= response.status_code < 400:
                        raise CollectorError(f"http_{response.status_code}")
                    response.raise_for_status()
                    content_length = response.headers.get("Content-Length")
                    try:
                        if content_length and int(content_length) > settings.PALWORLD_API_MAX_BYTES[dataset]:
                            raise CollectorError("too_large")
                    except ValueError:
                        raise CollectorError("invalid_content_length")
                    body = bytearray()
                    limit = settings.PALWORLD_API_MAX_BYTES[dataset]
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if time.monotonic() > deadline:
                            raise CollectorError("deadline")
                        body.extend(chunk)
                        if len(body) > limit:
                            raise CollectorError("too_large")
        except _DeadlineExpired as exc:
            raise CollectorError("deadline") from exc
        except CollectorError:
            raise
        except requests.Timeout as exc:
            raise CollectorError("timeout") from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            code = "auth" if status in {401, 403} else f"http_{status or 'error'}"
            raise CollectorError(code) from exc
        except requests.SSLError as exc:
            raise CollectorError("tls") from exc
        except requests.ConnectionError as exc:
            raise CollectorError("connection") from exc
        except requests.RequestException as exc:
            raise CollectorError("request") from exc
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CollectorError("invalid_json") from exc

    def _status(self):
        try:
            connection = self.socket_connection(
                (self.host, self.port),
                timeout=settings.PALWORLD_API_CONNECT_TIMEOUT,
            )
            connection.close()
            return True
        except OSError as exc:
            raise CollectorError("connection") from exc

    def close(self):
        self.session.close()


class PalworldCollector:
    def __init__(self, stop_event, client=None, monotonic=None):
        self.stop_event = stop_event
        self.client = client or PalworldClient()
        self.monotonic = monotonic or time.monotonic
        self.started_at = timezone.now().isoformat()
        self.dataset_state = {
            dataset: {
                "last_attempt": None,
                "last_success": None,
                "duration_ms": None,
                "failures": 0,
                "error": None,
            }
            for dataset in sorted(DATASETS)
        }
        self.next_run = {dataset: 0.0 for dataset in DATASETS}
        self.next_maintenance = 0.0

    def run(self):
        try:
            while not self.stop_event.is_set():
                close_old_connections()
                now = self.monotonic()
                for dataset in sorted(DATASETS, key=lambda key: self.next_run[key]):
                    if self.stop_event.is_set():
                        break
                    if self.next_run[dataset] > now:
                        continue
                    self.collect(dataset)
                    interval = settings.PALWORLD_API_INTERVALS[dataset]
                    self.next_run[dataset] = max(
                        self.next_run[dataset] + interval,
                        self.monotonic() + interval,
                    )
                if now >= self.next_maintenance:
                    try:
                        run_maintenance()
                    except OperationalError:
                        logger.warning("Collector maintenance delayed by database contention")
                    self.next_maintenance = self.monotonic() + 60
                self._write_state("running")
                self.stop_event.wait(1)
        finally:
            self._write_state("stopping")
            self.client.close()
            close_old_connections()

    def collect(self, dataset):
        state = self.dataset_state[dataset]
        started = self.monotonic()
        attempted_at = timezone.now()
        state["last_attempt"] = attempted_at.isoformat()
        try:
            value = self.client.fetch(dataset)
            source_clock = timezone.now()
            store_dataset(dataset, value, source_clock)
        except CollectorError as exc:
            if dataset == "status":
                try:
                    store_dataset("status", False, timezone.now())
                except OperationalError:
                    state["failures"] += 1
                    state["error"] = "database_busy"
                    logger.warning("Palworld REST status delayed by database contention")
                    return False
            state["failures"] += 1
            state["error"] = exc.code
            logger.warning("Palworld REST dataset %s failed: %s", dataset, exc.code)
            return False
        except IngestError:
            state["failures"] += 1
            state["error"] = "invalid_payload"
            logger.warning("Palworld REST dataset %s failed validation", dataset)
            return False
        except OperationalError:
            state["failures"] += 1
            state["error"] = "database_busy"
            logger.warning("Palworld REST dataset %s delayed by database contention", dataset)
            return False
        finally:
            state["duration_ms"] = max(0, int((self.monotonic() - started) * 1000))
        state["last_success"] = source_clock.isoformat()
        state["failures"] = 0
        state["error"] = None
        return True

    def _write_state(self, state):
        try:
            RuntimeState.objects.update_or_create(
                key="collector-status",
                defaults={"value": {
                    "state": state,
                    "started_at": self.started_at,
                    "heartbeat": timezone.now().isoformat(),
                    "datasets": self.dataset_state,
                }},
            )
        except OperationalError:
            logger.warning("Collector heartbeat delayed by database contention")
