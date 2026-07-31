import fcntl
import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from dashboard.collector import PalworldCollector


class Command(BaseCommand):
    help = "Poll the Palworld REST API and persist sanitized snapshots"

    def handle(self, *args, **options):
        stop_event = threading.Event()

        def stop(_signum, _frame):
            stop_event.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        with open(settings.COLLECTOR_LOCK_PATH, "w", encoding="ascii") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CommandError("another Palworld collector is already running") from exc
            PalworldCollector(stop_event).run()
