import time
from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import TestCase

from dashboard.models import LatestDataset, MetricSample, Player, PositionSample


class PublicApiTests(TestCase):
    def setUp(self):
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
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_snapshot_marks_missing_player_location(self):
        dataset = LatestDataset.objects.get(key="players")
        dataset.payload["players"][0]["location_x"] = 0
        dataset.payload["players"][0]["location_y"] = 0
        dataset.save(update_fields=["payload"])

        response = self.client.get("/api/v1/snapshot")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["players"][0]["location_available"])

    def test_history_and_trail(self):
        response = self.client.get("/api/v1/history?range=24h")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["samples"]), 1)
        response = self.client.get("/api/v1/player/public-player-id/trail?range=6h")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["positions"][0]["x"], -100)

    def test_invalid_ranges_are_rejected(self):
        self.assertEqual(self.client.get("/api/v1/history?range=forever").status_code, 400)
        self.assertEqual(
            self.client.get("/api/v1/player/public-player-id/trail?range=forever").status_code,
            400,
        )

    def test_stale_player_snapshot_hides_locations(self):
        stale = datetime.now(tz=dt_timezone.utc) - timedelta(minutes=10)
        dataset = LatestDataset.objects.get(key="players")
        dataset.source_clock = stale
        dataset.save(update_fields=["source_clock"])
        response = self.client.get("/api/v1/snapshot")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["players"], [])
        self.assertTrue(response.json()["status"]["players_stale"])

    def test_home_sets_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
