from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from dashboard.models import Player, PlayerSession, PositionSample, ServerEvent


@override_settings(SITE_AUTH_REQUIRED=False)
class PlayerDetailTests(TestCase):
    PUBLIC_ID = "a" * 24

    def setUp(self):
        cache.clear()
        now = timezone.now()
        self.player = Player.objects.create(
            public_id=self.PUBLIC_ID,
            name="Explorer",
            account_name="account",
            first_seen=now - timedelta(days=30),
            last_seen=now - timedelta(minutes=5),
            level=50,
            building_count=10,
            minutes_lifetime=240,
            session_count_lifetime=2,
            longest_session_minutes=90,
        )
        PlayerSession.objects.create(
            player=self.player,
            started_at=now - timedelta(hours=3),
            last_seen=now - timedelta(minutes=5),
            ended_at=now - timedelta(hours=2),
        )
        self.active_session = PlayerSession.objects.create(
            player=self.player,
            started_at=now - timedelta(minutes=30),
            last_seen=now,
            ended_at=None,
        )
        for index, ping in enumerate((12.0, 18.0, 25.0)):
            PositionSample.objects.create(
                player=self.player,
                source_clock=now - timedelta(minutes=10 * (index + 1)),
                x=-100.0,
                y=200.0,
                ping=ping,
                level=50,
                building_count=10,
            )
        ServerEvent.objects.create(
            player=self.player,
            event_type=ServerEvent.JOIN,
            source_clock=now - timedelta(minutes=30),
        )
        ServerEvent.objects.create(
            player=self.player,
            event_type=ServerEvent.LEAVE,
            source_clock=now - timedelta(hours=2),
        )

    def test_api_returns_player_profile(self):
        response = self.client.get(f"/api/v1/player/{self.PUBLIC_ID}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        player = payload["player"]
        self.assertEqual(player["name"], "Explorer")
        self.assertEqual(player["level"], 50)
        self.assertTrue(player["online"])
        self.assertGreater(player["current_session"], 0)
        self.assertEqual(player["minutes_lifetime"], 240)

    def test_api_returns_sessions_events_and_ping(self):
        payload = self.client.get(f"/api/v1/player/{self.PUBLIC_ID}").json()
        self.assertEqual(len(payload["sessions"]), 2)
        self.assertTrue(any(session["active"] for session in payload["sessions"]))
        self.assertEqual([event["type"] for event in payload["events"]], ["join", "leave"])
        pings = [sample["ping"] for sample in payload["ping"]]
        self.assertEqual(pings, [25.0, 18.0, 12.0])

    def test_api_returns_presence_grid(self):
        payload = self.client.get(f"/api/v1/player/{self.PUBLIC_ID}").json()
        grid = payload["presence"]["grid"]
        self.assertEqual(len(grid), 7)
        self.assertTrue(all(len(row) == 24 for row in grid))
        total_minutes = sum(sum(row) for row in grid)
        self.assertGreaterEqual(total_minutes, 8)
        self.assertLessEqual(total_minutes, 15)

    def test_api_404_for_unknown_or_invalid_id(self):
        self.assertEqual(self.client.get("/api/v1/player/" + "b" * 24).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/player/" + "z" * 24).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/player/not-a-player").status_code, 404)

    def test_page_renders_for_existing_player(self):
        response = self.client.get(f"/giocatori/{self.PUBLIC_ID}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-player-public-id="' + self.PUBLIC_ID + '"')
        self.assertContains(response, "player.js")

    def test_page_404_for_unknown_player(self):
        response = self.client.get("/giocatori/" + "b" * 24 + "/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Giocatore non trovato", response.content.decode())
