import fcntl
import logging
import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, close_old_connections

from dashboard.weekly_scheduler import mark_interrupted_run, run_due_report

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the persistent weekly report scheduler"

    def handle(self, *args, **options):
        stop_event = threading.Event()

        def stop(_signum, _frame):
            stop_event.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        with open(
            settings.WEEKLY_REPORT_SCHEDULER_LOCK_PATH, "w", encoding="ascii"
        ) as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CommandError(
                    "another weekly report scheduler is already running"
                ) from exc
            mark_interrupted_run()
            while not stop_event.is_set():
                close_old_connections()
                try:
                    run_due_report()
                except OperationalError:
                    logger.warning("Weekly report scheduler delayed by database error")
                finally:
                    close_old_connections()
                stop_event.wait(20)
