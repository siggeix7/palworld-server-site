from datetime import datetime, time, timedelta, timezone as datetime_timezone
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.models import UserProfile, WeeklyReportSchedule
from dashboard.weekly_scheduler import (
    claim_due_run,
    mark_interrupted_run,
    next_run_at,
    previous_run_at,
    run_due_report,
)

UTC = datetime_timezone.utc


class WeeklySchedulerTests(TestCase):
    def setUp(self):
        self.schedule = WeeklyReportSchedule.objects.get(id=1)

    def test_next_run_uses_configured_timezone(self):
        after = datetime(2026, 8, 9, 7, 0, tzinfo=UTC)
        result = next_run_at(0, time(8, 0), "Europe/Rome", after)
        self.assertEqual(result, datetime(2026, 8, 10, 6, 0, tzinfo=UTC))

    def test_nonexistent_dst_time_moves_to_first_valid_minute(self):
        after = datetime(2026, 3, 28, 12, 0, tzinfo=UTC)
        result = next_run_at(6, time(2, 30), "Europe/Rome", after)
        self.assertEqual(result, datetime(2026, 3, 29, 1, 0, tzinfo=UTC))
        self.assertEqual(result.astimezone(ZoneInfo("Europe/Rome")).strftime("%H:%M"), "03:00")

    def test_previous_run_preserves_local_week_across_dst(self):
        cutoff = datetime(2026, 3, 30, 6, 0, tzinfo=UTC)
        previous = previous_run_at(0, time(8, 0), "Europe/Rome", cutoff)
        self.assertEqual(previous, datetime(2026, 3, 23, 7, 0, tzinfo=UTC))
        self.assertEqual(cutoff - previous, timedelta(hours=167))

    def test_due_occurrence_is_claimed_only_once_and_advances_schedule(self):
        due = timezone.now() - timedelta(minutes=1)
        self.schedule.enabled = True
        self.schedule.next_run_at = due
        self.schedule.save()

        claimed = claim_due_run()
        second_claim = claim_due_run()

        self.assertEqual(claimed[0], due)
        self.assertIsNone(second_claim)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.last_status, WeeklyReportSchedule.RUNNING)
        self.assertGreater(self.schedule.next_run_at, timezone.now())

    def test_running_occurrence_is_marked_interrupted_after_restart(self):
        self.schedule.last_status = WeeklyReportSchedule.RUNNING
        self.schedule.save()
        mark_interrupted_run()
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.last_status, WeeklyReportSchedule.INTERRUPTED)
        self.assertEqual(self.schedule.last_error, "scheduler_restarted")

    @mock.patch("dashboard.weekly_scheduler.call_command")
    def test_report_uses_scheduled_cutoff_and_records_success(self, call_command):
        due = timezone.now() - timedelta(minutes=1)
        self.schedule.enabled = True
        self.schedule.timezone = "Europe/Rome"
        self.schedule.next_run_at = due
        self.schedule.save()

        self.assertTrue(run_due_report())

        call_command.assert_called_once_with(
            "send_weekly_report",
            until=due.isoformat(),
            since=mock.ANY,
            previous_since=mock.ANY,
            report_timezone="Europe/Rome",
        )
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.last_status, WeeklyReportSchedule.SUCCESS)


@override_settings(
    SITE_ADMIN_USERS={"admin"},
    CURRENT_TERMS_VERSION="test-terms",
)
class WeeklyScheduleApiTests(TestCase):
    password = "A-valid-test-password-782!"

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin", email="admin@example.com", password=self.password
        )
        self.member = User.objects.create_user(
            username="member", email="member@example.com", password=self.password
        )
        for user in (self.admin, self.member):
            UserProfile.objects.create(
                user=user,
                email_verified=True,
                approved=True,
                terms_version="test-terms",
                terms_accepted_at=timezone.now(),
            )

    def test_admin_can_read_and_update_schedule(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin-weekly-report-schedule"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["time"], "08:00")

        response = self.client.post(
            reverse("admin-weekly-report-schedule"),
            data={
                "enabled": True,
                "weekday": 4,
                "time": "19:30",
                "timezone": "Europe/Rome",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["weekday"], 4)
        self.assertEqual(response.json()["time"], "19:30")
        self.assertIsNotNone(response.json()["next_run_at"])

    def test_non_admin_is_rejected(self):
        self.client.force_login(self.member)
        self.assertEqual(
            self.client.get(reverse("admin-weekly-report-schedule")).status_code,
            403,
        )

    def test_update_requires_csrf_and_validates_all_fields(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        url = reverse("admin-weekly-report-schedule")
        valid = {
            "enabled": True,
            "weekday": 0,
            "time": "08:00",
            "timezone": "Europe/Rome",
        }
        self.assertEqual(
            csrf_client.post(url, valid, content_type="application/json").status_code,
            403,
        )

        self.client.force_login(self.admin)
        invalid = [
            {**valid, "weekday": 7},
            {**valid, "weekday": True},
            {**valid, "time": "8:00"},
            {**valid, "timezone": "Invalid/Timezone"},
            {**valid, "extra": True},
        ]
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(
                    self.client.post(url, body, content_type="application/json").status_code,
                    400,
                )
