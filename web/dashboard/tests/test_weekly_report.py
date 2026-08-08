from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from dashboard.models import GuildSnapshot, Player, PlayerSession, PositionSample


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SITE_ADMIN_USERS={"admin@example.com"},
)
class WeeklyReportTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def create_user(self, username, email):
        return get_user_model().objects.create_user(
            username=username,
            email=email,
            password="password",
            is_active=True,
        )

    def create_player(self, public_id, name, last_seen):
        return Player.objects.create(
            public_id=public_id,
            name=name,
            account_name=name,
            first_seen=last_seen - timedelta(days=30),
            last_seen=last_seen,
            level=50,
            building_count=10,
            minutes_lifetime=600,
            session_count_lifetime=4,
            longest_session_minutes=120,
        )

    def create_session(self, player, started_at, minutes):
        ended_at = started_at + timedelta(minutes=minutes)
        return PlayerSession.objects.create(
            player=player,
            started_at=started_at,
            last_seen=ended_at,
            ended_at=ended_at,
        )

    def test_command_sends_personalized_report_only_to_active_players(self):
        self.create_user("Explorer", "explorer@example.com")
        explorer = self.create_player("a" * 24, "Explorer", self.now)
        self.create_session(
            explorer, self.now - timedelta(days=3, hours=1), 60
        )
        self.create_session(
            explorer, self.now - timedelta(hours=5), 75
        )
        self.create_session(
            explorer, self.now - timedelta(days=9, hours=1), 90
        )

        old_timer = self.create_player(
            "b" * 24, "Old Timer", self.now - timedelta(days=10)
        )
        self.create_session(
            old_timer, self.now - timedelta(days=10), 100
        )

        ghost = self.create_player("c" * 24, "Ghost", self.now)
        self.create_session(ghost, self.now - timedelta(days=2), 45)

        PositionSample.objects.create(
            player=explorer,
            source_clock=self.now - timedelta(days=1),
            x=0,
            y=0,
            ping=40,
            level=50,
            building_count=10,
        )
        PositionSample.objects.create(
            player=explorer,
            source_clock=self.now - timedelta(days=2),
            x=0,
            y=0,
            ping=44,
            level=50,
            building_count=10,
        )
        GuildSnapshot.objects.create(
            payload={
                "schema_version": 3,
                "guilds": [
                    {
                        "group_id": "g" * 24,
                        "guild_name": "Explorers",
                        "base_count": 3,
                    }
                ],
                "bases": [],
                "players": [
                    {
                        "player_id": "p" * 24,
                        "player_name": "Explorer",
                        "guild_id": "g" * 24,
                        "is_admin": True,
                        "level": 55,
                        "exp": 1234567,
                        "owned_pal_count": 24,
                        "unused_status_points": 3,
                        "status_points": {"max_hp": 5, "attack": 2},
                    }
                ],
                "world": {},
                "diagnostics": {},
            }
        )

        call_command("send_weekly_report")

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["explorer@example.com"])
        self.assertIn("Il tuo report settimanale Palworld", email.subject)
        self.assertIn("Ciao Explorer", email.body)
        self.assertIn("2 ore e 15 minuti", email.body)
        self.assertIn("+50% rispetto alla settimana precedente", email.body)
        self.assertIn("Sessioni: 2", email.body)
        self.assertIn("più lunga: 75 minuti", email.body)
        self.assertIn("Giorni attivi:", email.body)
        self.assertIn("Livello: 50 · costruzioni: 10", email.body)
        self.assertIn("Ping medio: 42 ms", email.body)
        self.assertIn("1° su 2 giocatori attivi", email.body)
        self.assertIn("Explorers · 3 campi base", email.body)
        self.assertIn("Ghost — 45 minuti", email.body)
        self.assertNotIn("Old Timer", email.body)
        self.assertNotIn("Uptime", email.body)
        self.assertNotIn("Salute del flusso", email.body)
        self.assertNotIn("Giorno in-game", email.body)
        self.assertNotIn("Campi base", email.body)

        html_parts = [
            content for content, mimetype in email.alternatives if mimetype == "text/html"
        ]
        self.assertEqual(len(html_parts), 1)
        html = html_parts[0]
        self.assertIn("Le tue statistiche", html)
        self.assertIn("2 ore e 15 minuti", html)
        self.assertIn("Classifica della settimana", html)
        self.assertIn("(sei tu!)", html)
        self.assertNotIn("Salute del flusso", html)
        self.assertNotIn("Mondo", html)

    def test_command_reports_first_week_of_activity(self):
        self.create_user("Newbie", "newbie@example.com")
        newbie = self.create_player("d" * 24, "Newbie", self.now)
        self.create_session(newbie, self.now - timedelta(hours=2), 30)

        call_command("send_weekly_report")

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("30 minuti (prima settimana di attività)", email.body)
        self.assertIn("1° su 1 giocatore attivo", email.body)

    def test_command_skips_players_without_site_user(self):
        self.create_player("e" * 24, "Nobody", self.now)
        PlayerSession.objects.create(
            player=Player.objects.get(name="Nobody"),
            started_at=self.now - timedelta(hours=3),
            last_seen=self.now,
            ended_at=None,
        )

        call_command("send_weekly_report")

        self.assertEqual(len(mail.outbox), 0)

    def test_command_without_active_players_sends_nothing(self):
        self.create_user("Inactive", "inactive@example.com")
        inactive = self.create_player(
            "f" * 24, "Inactive", self.now - timedelta(days=30)
        )
        self.create_session(inactive, self.now - timedelta(days=30), 60)

        call_command("send_weekly_report")

        self.assertEqual(len(mail.outbox), 0)
