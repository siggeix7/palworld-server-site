import fcntl
import logging
import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, close_old_connections

from dashboard.services import cleanup_if_due


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the independent retention cleanup loop"

    def handle(self, *args, **options):
        del args, options
        stop_event = threading.Event()

        def stop(_signum, _frame):
            stop_event.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        with open(settings.RETENTION_CLEANUP_LOCK_PATH, "w", encoding="ascii") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CommandError("another retention cleanup is already running") from exc
            while not stop_event.is_set():
                close_old_connections()
                try:
                    cleanup_if_due()
                except OperationalError:
                    logger.warning("Retention cleanup delayed by database error")
                finally:
                    close_old_connections()
                stop_event.wait(60)
