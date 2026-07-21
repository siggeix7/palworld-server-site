from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.models import (
    LatestDataset,
    MetricSample,
    Player,
    PlayerSession,
    PositionSample,
    UserProfile,
)


@override_settings(SITE_AUTH_REQUIRED=False)
class AnalyticsApiTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.player = Player.objects.create(
            public_id="leaderboard-player",
            name="TopExplorer",
            account_name="top-account",
            first_seen=self.now - timedelta(days=40),
            last_seen=self.now,
            level=50,
            building_count=10,
        )
        PlayerSession.objects.create(
            player=self.player,
            started_at=self.now - timedelta(minutes=120),
            last_seen=self.now,
        )
        PlayerSession.objects.create(
            player=self.player,
            started_at=self.now - timedelta(days=10),
            last_seen=self.now - timedelta(days=10) + timedelta(minutes=60),
            ended_at=self.now - timedelta(days=10) + timedelta(minutes=60),
        )
        PositionSample.objects.create(
            player=self.player,
            source_clock=self.now,
            x=-100,
            y=200,
            ping=22,
            level=50,
            building_count=10,
        )
        MetricSample.objects.create(
            source_clock=self.now,
            current_players=4,
            max_players=8,
            server_fps=58,
            server_fps_average=57,
            frame_time=17,
            world_days=100,
            base_camps=4,
            uptime=7200,
        )
        LatestDataset.objects.create(
            key="settings",
            payload={"ExpRate": 2.0, "ServerPlayerMaxNum": 16, "bIsPvP": False},
            source_clock=self.now,
        )
        LatestDataset.objects.create(
            key="metrics",
            payload={"days": 100, "uptime": 7200},
            source_clock=self.now,
        )

    def test_leaderboard_ranks_by_playtime(self):
        response = self.client.get(reverse("leaderboard-api"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("by_playtime", payload)
        self.assertEqual(payload["total_players"], 1)
        top = payload["by_playtime"]["30d"][0]
        self.assertEqual(top["name"], "TopExplorer")
        self.assertGreater(top["minutes_30d"], 0)
        self.assertEqual(len(payload["by_level"]), 1)

    def test_activity_heatmap_returns_grid(self):
        response = self.client.get(reverse("activity-heatmap") + "?range=30d")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["grid"]), 7)
        self.assertEqual(len(payload["grid"][0]), 24)
        self.assertGreaterEqual(payload["session_count"], 1)
        self.assertEqual(payload["range"], "30d")
        self.assertEqual(
            self.client.get(reverse("activity-heatmap") + "?range=forever").status_code,
            400,
        )

    def test_map_heatmap_returns_cells(self):
        response = self.client.get(reverse("map-heatmap") + "?range=24h")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["grid_size"], 48)
        self.assertGreater(len(payload["cells"]), 0)
        self.assertGreater(payload["max_count"], 0)
        self.assertEqual(payload["bounds"]["min_x"], -1099400)
        self.assertEqual(
            self.client.get(reverse("map-heatmap") + "?range=1y").status_code,
            400,
        )

    def test_telemetry_stats_reports_uptime_and_stability(self):
        response = self.client.get(reverse("telemetry-stats"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pct_24h", payload["uptime"])
        self.assertIsNotNone(payload["fps"]["mean_24h"])
        self.assertIsNotNone(payload["fps"]["stability_cv_24h"])
        self.assertEqual(payload["world"]["day"], 100)

    def test_world_diff_lists_only_changed_settings(self):
        response = self.client.get(reverse("world-diff"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["has_settings"])
        keys = [diff["key"] for diff in payload["diffs"]]
        self.assertIn("ExpRate", keys)
        self.assertIn("ServerPlayerMaxNum", keys)
        self.assertNotIn("bIsPvP", keys)
        self.assertEqual(payload["total"], 2)


@override_settings(
    SITE_AUTH_REQUIRED=True,
    SITE_ADMIN_USERS={"admin@example.com"},
    CSRF_TRUSTED_ORIGINS=["https://palworld.example.com"],
    PUBLIC_SITE_URL="https://palworld.example.com",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class NewPageTests(TestCase):
    password = "A-valid-test-password-782!"

    def create_user(self, username="member", email="member@example.com"):
        user = get_user_model().objects.create_user(
            username=username, email=email, password=self.password
        )
        UserProfile.objects.create(user=user, email_verified=True, approved=True)
        return user

    def setUp(self):
        self.member = self.create_user()
        self.client.force_login(self.member)

    def test_leaderboard_page_renders(self):
        response = self.client.get(reverse("leaderboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Classifica")
        self.assertContains(response, "leaderboard.js")

    def test_peak_hours_page_renders(self):
        response = self.client.get(reverse("peak-hours"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Orari di punta")
        self.assertContains(response, "peak_hours.js")

    def test_navbar_includes_new_sections(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, reverse("leaderboard"))
        self.assertContains(response, reverse("peak-hours"))

    def test_map_page_has_external_links_and_heatmap_controls(self):
        response = self.client.get(reverse("map"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mapgenie.io")
        self.assertContains(response, "palworld.gg")
        self.assertContains(response, "showHeatmap")
        self.assertContains(response, "fullscreenMap")
