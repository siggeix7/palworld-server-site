from datetime import timedelta

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from dashboard.models import LatestDataset, MetricSample, Player, PlayerSession


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SITE_ADMIN_USERS={"admin@example.com"},
)
class WeeklyReportTests(TestCase):
    def setUp(self):
        now = timezone.now()
        for index in range(60):
            MetricSample.objects.create(
                source_clock=now - timedelta(seconds=3600 - index * 60),
                current_players=2 + (index % 3),
                max_players=16,
                server_fps=55,
                server_fps_average=54,
                frame_time=18,
                world_days=100,
                base_camps=8,
                uptime=7200,
            )
        LatestDataset.objects.create(
            key="metrics",
            payload={"days": 5702, "basecampnum": 8},
            source_clock=now,
        )
        self.player = Player.objects.create(
            public_id="a" * 24,
            name="Explorer",
            account_name="account",
            first_seen=now - timedelta(days=2),
            last_seen=now - timedelta(minutes=30),
            level=50,
            building_count=10,
            minutes_lifetime=60,
            session_count_lifetime=1,
            longest_session_minutes=60,
        )
        PlayerSession.objects.create(
            player=self.player,
            started_at=now - timedelta(hours=2),
            last_seen=now - timedelta(hours=1),
            ended_at=now - timedelta(hours=1),
        )
        Player.objects.create(
            public_id="b" * 24,
            name="Old Timer",
            account_name="",
            first_seen=now - timedelta(days=400),
            last_seen=now - timedelta(days=10),
            level=20,
            building_count=1,
            minutes_lifetime=100,
            session_count_lifetime=1,
            longest_session_minutes=100,
        )

    def test_command_sends_report_to_admin_recipients(self):
        call_command("send_weekly_report")
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["admin@example.com"])
        self.assertIn("Report settimanale Palworld", email.subject)
        self.assertIn("Explorer", email.body)
        self.assertNotIn("Old Timer", email.body)
        self.assertIn("Uptime 7 giorni", email.body)
        self.assertIn("Uptime 24h: 4,1%", email.body)
        self.assertIn("Giorno in-game: 5702", email.body)
        self.assertIn("Campi base: 8", email.body)

    def test_command_fails_without_recipients(self):
        with override_settings(SITE_ADMIN_USERS=set()):
            with self.assertRaises(CommandError):
                call_command("send_weekly_report")
