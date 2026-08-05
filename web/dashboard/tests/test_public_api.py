import time
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from dashboard.models import (
    GuildSnapshot,
    LatestDataset,
    MetricSample,
    Player,
    PlayerSession,
    PositionSample,
)
from dashboard.services import recompute_lifetime_rollups


@override_settings(SITE_AUTH_REQUIRED=False)
class PublicApiTests(TestCase):
    def setUp(self):
        cache.clear()
        now = datetime.fromtimestamp(int(time.time()), tz=dt_timezone.utc)
        LatestDataset.objects.create(
            key="status", payload={"reachable": True}, source_clock=now
        )
        LatestDataset.objects.create(
            key="metrics",
            payload={
                "currentplayernum": 1,
                "maxplayernum": 8,
                "serverfps": 59,
                "serverfpsaverage": 58.5,
                "serverframetime": 16.8,
                "days": 100,
                "basecampnum": 4,
                "uptime": 7200,
            },
            source_clock=now,
        )
        LatestDataset.objects.create(
            key="players",
            payload={
                "players": [
                    {
                        "id": "public-player-id",
                        "name": "Explorer",
                        "accountName": "account",
                        "ping": 22,
                        "location_x": -100,
                        "location_y": 200,
                        "level": 50,
                        "building_count": 10,
                    }
                ]
            },
            source_clock=now,
        )
        MetricSample.objects.create(
            source_clock=now,
            current_players=1,
            max_players=8,
            server_fps=59,
            server_fps_average=58.5,
            frame_time=16.8,
            world_days=100,
            base_camps=4,
            uptime=7200,
        )
        self.player = Player.objects.create(
            public_id="public-player-id",
            name="Explorer",
            account_name="account",
            first_seen=now,
            last_seen=now,
            level=50,
            building_count=10,
        )
        PositionSample.objects.create(
            player=self.player,
            source_clock=now,
            x=-100,
            y=200,
            ping=22,
            level=50,
            building_count=10,
        )

    def test_snapshot_returns_public_state(self):
        response = self.client.get("/api/v1/snapshot")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["status"]["online"])
        self.assertEqual(payload["players"][0]["name"], "Explorer")
        self.assertTrue(payload["players"][0]["location_available"])
        self.assertEqual(payload["summary_24h"]["average_players"], 1.0)
        self.assertEqual(payload["summary_24h"]["minimum_fps"], 59.0)
        expected_start = LatestDataset.objects.get(key="metrics").source_clock - timedelta(
            seconds=7200
        )
        self.assertEqual(
            payload["status"]["started_at"],
            expected_start.isoformat().replace("+00:00", "Z"),
        )
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])

    def test_snapshot_marks_missing_player_location(self):
        dataset = LatestDataset.objects.get(key="players")
        dataset.payload["players"][0]["location_x"] = 0
        dataset.payload["players"][0]["location_y"] = 0
        dataset.save(update_fields=["payload"])

        response = self.client.get("/api/v1/snapshot")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["players"][0]["location_available"])

    def test_snapshot_serves_repeated_polls_from_cache(self):
        self.client.get("/api/v1/snapshot")
        with self.assertNumQueries(0):
            response = self.client.get("/api/v1/snapshot")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["status"]["online"])

    def test_history(self):
        response = self.client.get("/api/v1/history?range=24h")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])
        self.assertEqual(len(response.json()["samples"]), 1)
        self.assertEqual(response.json()["fps_health"]["state"], "calibrating")

    def test_fps_health_uses_cadence_and_breaks_at_data_gaps(self):
        now = datetime(2026, 7, 20, 12, 0, tzinfo=dt_timezone.utc)
        MetricSample.objects.all().delete()
        timestamps = [now - timedelta(minutes=20) + timedelta(seconds=20 * index) for index in range(10)]
        timestamps += [now - timedelta(minutes=5) + timedelta(seconds=20 * index) for index in range(16)]
        for index, timestamp in enumerate(timestamps):
            fps = 20 if index < 10 else 60
            MetricSample.objects.create(
                source_clock=timestamp,
                current_players=1,
                max_players=8,
                server_fps=fps,
                server_fps_average=fps,
                frame_time=1000 / fps,
                world_days=100,
                base_camps=4,
                uptime=7200,
            )

        with mock.patch("dashboard.views.timezone.now", return_value=now):
            response = self.client.get("/api/v1/history?range=7d")

        self.assertEqual(response.status_code, 200)
        health = response.json()["fps_health"]
        self.assertEqual(health["state"], "ok")
        self.assertEqual(health["nominal_cadence_seconds"], 20)
        self.assertEqual(health["gap_threshold_seconds"], 60)
        self.assertEqual(health["longest_dip_seconds"], 200)
        self.assertLessEqual(health["score"], 30)

    def test_sparse_and_future_fps_samples_do_not_create_false_coverage(self):
        now = datetime(2026, 7, 20, 12, 0, tzinfo=dt_timezone.utc)
        MetricSample.objects.all().delete()
        for timestamp in [
            now - timedelta(minutes=10),
            now - timedelta(minutes=5),
            now,
            now + timedelta(minutes=1),
        ]:
            MetricSample.objects.create(
                source_clock=timestamp,
                current_players=0,
                max_players=8,
                server_fps=60,
                server_fps_average=60,
                frame_time=16.7,
                world_days=100,
                base_camps=4,
                uptime=7200,
            )

        with mock.patch("dashboard.views.timezone.now", return_value=now):
            response = self.client.get("/api/v1/history?range=90d")

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])
        payload = response.json()
        self.assertEqual(len(payload["samples"]), 3)
        self.assertEqual(payload["fps_health"]["state"], "calibrating")
        self.assertEqual(payload["fps_health"]["coverage_seconds"], 60)
        self.assertEqual(payload["fps_health"]["gap_threshold_seconds"], 60)
        self.assertTrue(payload["samples"][1]["gap_before"])

    def test_player_archive_returns_periods_and_rolling_minutes(self):
        now = datetime(2026, 7, 20, 12, 0, tzinfo=dt_timezone.utc)
        sessions = [
            (now - timedelta(minutes=10), now, None),
            (
                now - timedelta(days=2),
                now - timedelta(days=2) + timedelta(minutes=120),
                now - timedelta(days=2) + timedelta(minutes=120),
            ),
            (
                now - timedelta(days=30, minutes=30),
                now - timedelta(days=30) + timedelta(minutes=30),
                now - timedelta(days=30) + timedelta(minutes=30),
            ),
            (
                now - timedelta(days=40),
                now - timedelta(days=40) + timedelta(minutes=60),
                now - timedelta(days=40) + timedelta(minutes=60),
            ),
            (
                now - timedelta(days=400),
                now - timedelta(days=400) + timedelta(minutes=30),
                now - timedelta(days=400) + timedelta(minutes=30),
            ),
        ]
        for started_at, last_seen, ended_at in sessions:
            PlayerSession.objects.create(
                player=self.player,
                started_at=started_at,
                last_seen=last_seen,
                ended_at=ended_at,
            )
        recompute_lifetime_rollups(self.player)

        stale_player = Player.objects.create(
            public_id="stale-player-id",
            name="Stale Explorer",
            account_name="stale-account",
            first_seen=now - timedelta(hours=3),
            last_seen=now - timedelta(hours=2),
        )
        PlayerSession.objects.create(
            player=stale_player,
            started_at=now - timedelta(hours=3),
            last_seen=now - timedelta(hours=2),
        )
        recompute_lifetime_rollups(stale_player)

        with mock.patch("dashboard.views.timezone.now", return_value=now):
            response = self.client.get("/api/v1/players")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["windows"], {"month_days": 30, "year_days": 365})
        player = next(
            entry for entry in payload["players"] if entry["id"] == "public-player-id"
        )
        self.assertTrue(player["online"])
        self.assertEqual(player["session_count"], 5)
        self.assertEqual(player["minutes_30d"], 160)
        self.assertEqual(player["minutes_365d"], 250)
        self.assertEqual(player["minutes_all"], 280)
        self.assertEqual(player["building_count"], 10)
        self.assertEqual(player["average_session_minutes"], 56)
        self.assertEqual(player["longest_session_minutes"], 120)
        self.assertEqual(player["active_days_30d"], 3)
        self.assertEqual(len(player["periods"]), 4)
        self.assertTrue(player["periods"][0]["active"])
        self.assertIsNone(player["periods"][0]["ended_at"])

        stale = next(
            entry for entry in payload["players"] if entry["id"] == "stale-player-id"
        )
        self.assertFalse(stale["online"])
        self.assertEqual(stale["minutes_all"], 61)
        self.assertFalse(stale["periods"][0]["active"])
        self.assertIsNotNone(stale["periods"][0]["ended_at"])

    def test_player_archive_merges_save_progression_and_includes_save_only_players(self):
        GuildSnapshot.objects.create(
            payload={
                "schema_version": 3,
                "guilds": [{
                    "group_id": "aaaaaaaaaaaaaaaaaaaa",
                    "guild_name": "Explorers",
                    "players": [],
                }],
                "bases": [],
                "players": [
                    {
                        "player_id": "bbbbbbbbbbbbbbbbbbbb",
                        "player_name": "Explorer",
                        "guild_id": "aaaaaaaaaaaaaaaaaaaa",
                        "is_admin": True,
                        "level": 55,
                        "exp": 1234567,
                        "owned_pal_count": 24,
                        "unused_status_points": 3,
                        "status_points": {"max_hp": 5, "attack": 2},
                    },
                    {
                        "player_id": "cccccccccccccccccccc",
                        "player_name": "Historical Explorer",
                        "guild_id": "aaaaaaaaaaaaaaaaaaaa",
                        "is_admin": False,
                        "level": 31,
                        "exp": 456789,
                        "owned_pal_count": 8,
                        "unused_status_points": 0,
                        "status_points": {"work_speed": 4},
                    },
                ],
                "world": {},
                "diagnostics": {},
            }
        )

        payload = self.client.get("/api/v1/players").json()
        self.assertEqual(len(payload["players"]), 2)
        current = next(
            player for player in payload["players"] if player["name"] == "Explorer"
        )
        self.assertEqual(current["id"], "public-player-id")
        self.assertEqual(current["level"], 55)
        self.assertEqual(current["building_count"], 10)
        self.assertEqual(current["exp"], 1234567)
        self.assertEqual(current["owned_pal_count"], 24)
        self.assertEqual(current["guild_name"], "Explorers")
        self.assertTrue(current["is_guild_admin"])
        self.assertFalse(current["save_only"])
        self.assertEqual(current["ping_7d"]["average"], 22.0)

        historical = next(
            player
            for player in payload["players"]
            if player["name"] == "Historical Explorer"
        )
        self.assertEqual(historical["id"], "save-cccccccccccccccccccc")
        self.assertTrue(historical["save_only"])
        self.assertTrue(historical["save_available"])
        self.assertIsNone(historical["first_seen"])
        self.assertIsNone(historical["last_seen"])
        self.assertEqual(historical["level"], 31)
        self.assertEqual(historical["session_count"], 0)
        self.assertEqual(historical["status_points"], {"work_speed": 4})

    def test_player_archive_does_not_guess_ambiguous_name_matches(self):
        Player.objects.create(
            public_id="duplicate-player-id",
            name="Explorer",
            first_seen=self.player.first_seen,
            last_seen=self.player.last_seen,
        )
        GuildSnapshot.objects.create(
            payload={
                "schema_version": 3,
                "guilds": [],
                "bases": [],
                "players": [{
                    "player_id": "dddddddddddddddddddd",
                    "player_name": "Explorer",
                    "guild_id": "",
                    "is_admin": False,
                    "level": 60,
                    "exp": 1,
                    "owned_pal_count": 1,
                    "unused_status_points": 0,
                    "status_points": {},
                }],
                "world": {},
                "diagnostics": {},
            }
        )
        players = self.client.get("/api/v1/players").json()["players"]
        self.assertEqual(len(players), 3)
        self.assertEqual(sum(player["save_only"] for player in players), 1)

    def test_invalid_ranges_are_rejected(self):
        self.assertEqual(self.client.get("/api/v1/history?range=forever").status_code, 400)

    def test_stale_player_snapshot_hides_locations(self):
        stale = datetime.now(tz=dt_timezone.utc) - timedelta(minutes=10)
        dataset = LatestDataset.objects.get(key="players")
        dataset.source_clock = stale
        dataset.save(update_fields=["source_clock"])
        response = self.client.get("/api/v1/snapshot")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["players"], [])
        self.assertTrue(response.json()["status"]["players_stale"])

    def test_spa_shell_sets_security_headers_without_legacy_footer(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertTemplateUsed(response, "dashboard/app.html")
        self.assertContains(response, "dashboard/live-map/live-map.js")
        self.assertNotContains(response, "THIRD_PARTY_NOTICES.txt")
