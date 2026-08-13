import logging
from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from .models import WeeklyReportSchedule

logger = logging.getLogger(__name__)
UTC = datetime_timezone.utc


def _local_occurrence(day, run_time, zone):
    naive = datetime.combine(day, run_time)
    candidate = naive.replace(tzinfo=zone, fold=0)
    while candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
        naive += timedelta(minutes=1)
        candidate = naive.replace(tzinfo=zone, fold=0)
    return candidate.astimezone(UTC)


def next_run_at(weekday, run_time, timezone_name, after):
    zone = ZoneInfo(timezone_name)
    local_after = after.astimezone(zone)
    days_ahead = (weekday - local_after.weekday()) % 7
    candidate = _local_occurrence(
        local_after.date() + timedelta(days=days_ahead), run_time, zone
    )
    if candidate <= after:
        candidate = _local_occurrence(
            local_after.date() + timedelta(days=days_ahead + 7), run_time, zone
        )
    return candidate


def previous_run_at(weekday, run_time, timezone_name, before):
    zone = ZoneInfo(timezone_name)
    local_before = before.astimezone(zone)
    days_back = (local_before.weekday() - weekday) % 7
    candidate = _local_occurrence(
        local_before.date() - timedelta(days=days_back), run_time, zone
    )
    if candidate >= before:
        candidate = _local_occurrence(
            local_before.date() - timedelta(days=days_back + 7), run_time, zone
        )
    return candidate


def ensure_next_run(schedule, now=None):
    now = now or timezone.now()
    if not schedule.enabled:
        schedule.next_run_at = None
    elif schedule.next_run_at is None:
        schedule.next_run_at = next_run_at(
            schedule.weekday, schedule.run_time, schedule.timezone, now
        )
    return schedule.next_run_at


def mark_interrupted_run():
    now = timezone.now()
    WeeklyReportSchedule.objects.filter(
        id=1, last_status=WeeklyReportSchedule.RUNNING
    ).update(
        last_status=WeeklyReportSchedule.INTERRUPTED,
        last_finished_at=now,
        last_error="scheduler_restarted",
        updated_at=now,
    )


def claim_due_run(now=None):
    now = now or timezone.now()
    with transaction.atomic():
        schedule, _ = WeeklyReportSchedule.objects.select_for_update().get_or_create(id=1)
        if not schedule.enabled:
            if schedule.next_run_at is not None:
                schedule.next_run_at = None
                schedule.save(update_fields=["next_run_at", "updated_at"])
            return None
        if schedule.next_run_at is None:
            ensure_next_run(schedule, now)
            schedule.save(update_fields=["next_run_at", "updated_at"])
            return None
        if schedule.next_run_at > now:
            return None

        scheduled_for = schedule.next_run_at
        following = next_run_at(
            schedule.weekday, schedule.run_time, schedule.timezone, scheduled_for
        )
        while following <= now:
            scheduled_for = following
            following = next_run_at(
                schedule.weekday, schedule.run_time, schedule.timezone, scheduled_for
            )

        schedule.next_run_at = following
        schedule.last_scheduled_for = scheduled_for
        schedule.last_started_at = now
        schedule.last_finished_at = None
        schedule.last_status = WeeklyReportSchedule.RUNNING
        schedule.last_error = ""
        schedule.save(
            update_fields=[
                "next_run_at",
                "last_scheduled_for",
                "last_started_at",
                "last_finished_at",
                "last_status",
                "last_error",
                "updated_at",
            ]
        )
        return (
            scheduled_for,
            schedule.weekday,
            schedule.run_time,
            schedule.timezone,
        )


def run_due_report(now=None):
    claimed = claim_due_run(now)
    if claimed is None:
        return False
    scheduled_for, weekday, run_time, timezone_name = claimed
    since = previous_run_at(weekday, run_time, timezone_name, scheduled_for)
    previous_since = previous_run_at(weekday, run_time, timezone_name, since)
    status = WeeklyReportSchedule.SUCCESS
    error = ""
    try:
        call_command(
            "send_weekly_report",
            until=scheduled_for.isoformat(),
            since=since.isoformat(),
            previous_since=previous_since.isoformat(),
            report_timezone=timezone_name,
        )
    except Exception:
        status = WeeklyReportSchedule.FAILED
        error = "report_command_failed"
        logger.exception("Scheduled weekly report failed")
    WeeklyReportSchedule.objects.filter(
        id=1,
        last_scheduled_for=scheduled_for,
        last_status=WeeklyReportSchedule.RUNNING,
    ).update(
        last_finished_at=timezone.now(),
        last_status=status,
        last_error=error,
        updated_at=timezone.now(),
    )
    return True
