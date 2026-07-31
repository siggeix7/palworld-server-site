import json
from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from dashboard.models import (
    GuildSnapshot,
    LatestDataset,
    MetricSample,
    Player,
    PlayerSession,
    PositionSample,
    ServerEvent,
)
from dashboard.services import IngestError, store_dataset


@override_settings(
    ROOT_URLCONF="palworld_site.ingest_urls",
    PRIVATE_API_TOKEN="test-private-token",
    PLAYER_HASH_SECRET="test-player-secret",
    SITE_AUTH_REQUIRED=False,
)
class GuildIngestTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.headers = {"HTTP_AUTHORIZATION": "Bearer test-private-token"}

    def post(self, payload, content_type="application/json", **headers):
        return self.client.post(
            "/api/v1/guild/ingest",
            data=json.dumps(payload) if not isinstance(payload, str) else payload,
            content_type=content_type,
            **{**self.headers, **headers},
        )

    def test_stores_minimized_guild_base_and_player_data(self):
        payload = {
            "schema_version": 3,
            "guilds": [{
                "group_id": "a" * 20,
                "guild_name": "Explorers",
                "pal_count": 24,
                "worker_count": 8,
                "players": [],
            }],
            "bases": [{
                "base_id": "b" * 20,
                "group_id": "a" * 20,
                "name": "Forte Nord",
                "location_x": -100,
                "location_y": 200,
                "worker_count": 8,
                "work_types": [],
                "raid_active": False,
            }],
            "players": [{
                "player_id": "c" * 20,
                "player_name": "Historical Explorer",
                "guild_id": "a" * 20,
                "is_admin": False,
                "level": 42,
                "exp": 987654,
                "owned_pal_count": 17,
                "unused_status_points": 2,
                "status_points": {"max_hp": 5, "attack": 3},
            }],
            "world": {"active_raid_count": 0},
            "diagnostics": {"unresolved_worker_count": 0},
        }
        response = self.post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(GuildSnapshot.objects.get(pk=1).payload, payload)

    def test_rejects_raw_ids_malformed_payloads_and_bad_auth(self):
        raw_payload = {
            "schema_version": 2,
            "guilds": [{
                "group_id": "raw-guild-uuid",
                "guild_name": "Explorers",
                "players": [],
            }],
            "bases": [],
            "world": {},
            "diagnostics": {},
        }
        self.assertEqual(self.post(raw_payload).status_code, 422)
        self.assertEqual(self.post({"guilds": {}, "bases": []}).status_code, 422)
        self.assertEqual(self.post("{}", content_type="text/plain").status_code, 415)
        response = self.client.post(
            "/api/v1/guild/ingest",
            data="{}",
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer wrong-token",
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(GuildSnapshot.objects.exists())

    @override_settings(PRIVATE_API_TOKEN="")
    def test_rejects_when_private_token_is_not_configured(self):
        self.assertEqual(self.post({"guilds": [], "bases": []}).status_code, 503)


@override_settings(PLAYER_HASH_SECRET="test-player-secret")
class DirectDatasetTests(TestCase):
    def test_stores_metrics_status_and_history(self):
        clock = timezone.now()
        metrics = {
            "currentplayernum": 2,
            "maxplayernum": 32,
            "serverfps": 58.4,
            "serverframetime": 17.1,
            "days": 12,
            "uptime": 500,
        }
        self.assertTrue(store_dataset("metrics", metrics, clock))
        self.assertTrue(store_dataset("status", True, clock))
        self.assertEqual(LatestDataset.objects.get(key="metrics").payload["serverfps"], 58.4)
        self.assertEqual(MetricSample.objects.get(source_clock=clock).current_players, 2)
        self.assertTrue(LatestDataset.objects.get(key="status").payload["reachable"])

    def test_older_and_invalid_payloads_do_not_replace_last_good_data(self):
        clock = timezone.now()
        store_dataset("players", {"players": []}, clock)
        self.assertFalse(store_dataset(
            "players",
            {"players": [{"name": "Old"}]},
            clock - timedelta(minutes=1),
        ))
        with self.assertRaises(IngestError):
            store_dataset("players", {"players": "invalid"})
        self.assertEqual(LatestDataset.objects.get(key="players").payload, {"players": []})

    def test_sanitizes_server_metadata_and_settings(self):
        store_dataset("info", {
            "version": "v1\x00",
            "servername": "Server\nName",
            "description": "Description\t",
            "worldguid": "private-world-guid",
        })
        store_dataset("settings", {
            "Difficulty": "Normal",
            "AdminPassword": "private-password",
            "PublicIP": "192.0.2.10",
        })
        serialized = json.dumps({
            "info": LatestDataset.objects.get(key="info").payload,
            "settings": LatestDataset.objects.get(key="settings").payload,
        })
        for private in ("private-world-guid", "private-password", "192.0.2.10"):
            self.assertNotIn(private, serialized)

    def test_sanitizes_players_and_infers_sessions(self):
        raw_user_id = "76561198000000000"
        clock = timezone.now()
        store_dataset("players", {"players": [{
            "userId": raw_user_id,
            "playerId": "raw-player-id",
            "name": "Explorer",
            "accountName": "Account",
            "ping": 22.5,
            "location_x": 10,
            "location_y": 20,
            "level": 12,
            "building_count": 4,
            "ip": "192.0.2.20",
        }]}, clock)
        player = Player.objects.get()
        self.assertNotEqual(player.public_id, raw_user_id)
        self.assertEqual(len(player.public_id), 24)
        self.assertTrue(PlayerSession.objects.filter(player=player, ended_at__isnull=True).exists())
        self.assertTrue(PositionSample.objects.filter(player=player).exists())
        self.assertTrue(ServerEvent.objects.filter(player=player, event_type="join").exists())
        serialized = json.dumps(LatestDataset.objects.get(key="players").payload)
        self.assertNotIn(raw_user_id, serialized)
        self.assertNotIn("raw-player-id", serialized)
        self.assertNotIn("192.0.2.20", serialized)

    def test_player_rollups_track_lifetime_playtime_across_pruning(self):
        start = timezone.now() - timedelta(minutes=10)
        store_dataset("players", {"players": [{
            "userId": "u1", "playerId": "p1", "name": "Rollup Tester",
            "location_x": 1, "location_y": 2, "level": 1, "ping": 5,
        }]}, start)
        player = Player.objects.get()
        self.assertEqual(player.session_count_lifetime, 1)
        self.assertEqual(player.minutes_lifetime, 0)

        end = timezone.now()
        store_dataset("players", {"players": []}, end)
        player.refresh_from_db()
        session = PlayerSession.objects.get(player=player)
        self.assertIsNotNone(session.ended_at)
        expected_minutes = int((session.ended_at - session.started_at).total_seconds()) // 60
        self.assertEqual(player.minutes_lifetime, expected_minutes)
        self.assertEqual(player.longest_session_minutes, expected_minutes)
        self.assertGreater(player.session_count_lifetime, 0)

        PlayerSession.objects.filter(started_at__lt=end - timedelta(seconds=1), ended_at__isnull=False).delete()
        player.refresh_from_db()
        self.assertFalse(PlayerSession.objects.filter(player=player).exists())
        self.assertEqual(player.minutes_lifetime, expected_minutes)
        self.assertEqual(player.session_count_lifetime, 1)


@override_settings(
    PRIVATE_API_TOKEN="test-private-token",
    SITE_AUTH_REQUIRED=False,
)
class PortSeparationTests(TestCase):
    def test_private_urlconf_exposes_only_control_health_and_guild_ingest(self):
        with override_settings(ROOT_URLCONF="palworld_site.ingest_urls"):
            self.assertEqual(self.client.get("/").status_code, 404)
            self.assertEqual(self.client.get("/mappa/").status_code, 404)
            self.assertEqual(self.client.get("/api/v1/collector/status").status_code, 401)

    def test_public_urlconf_does_not_expose_private_ingest_or_control(self):
        with override_settings(ROOT_URLCONF="palworld_site.urls"):
            self.assertEqual(self.client.post("/api/v1/guild/ingest").status_code, 404)
            self.assertEqual(self.client.get("/api/v1/collector/status").status_code, 404)
