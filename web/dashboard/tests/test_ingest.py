import json
import time

from django.test import Client, TestCase, override_settings

from dashboard.models import LatestDataset, MetricSample, Player, PlayerSession, PositionSample, ServerEvent


def record(dataset, value, clock=None, name=None):
    return {
        "host": {"host": "palworld", "name": "Palworld"},
        "groups": ["Games"],
        "item_tags": [
            {"tag": "integration", "value": "palworld-site"},
            {"tag": "dataset", "value": dataset},
        ],
        "itemid": 10001,
        "name": name or f"Palworld: {dataset.title()}",
        "clock": clock or int(time.time()),
        "ns": 0,
        "value": json.dumps(value) if isinstance(value, (dict, list)) else value,
        "type": 4,
    }


def ndjson(*records):
    return "\n".join(json.dumps(value) for value in records)


@override_settings(
    ROOT_URLCONF="palworld_site.ingest_urls",
    ZABBIX_CONNECTOR_TOKEN="test-connector-token",
    PLAYER_HASH_SECRET="test-player-secret",
)
class IngestTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.headers = {"HTTP_AUTHORIZATION": "Bearer test-connector-token"}

    def post(self, body, **headers):
        return self.client.post(
            "/api/v1/zabbix/ingest",
            data=body,
            content_type="application/x-ndjson",
            **{**self.headers, **headers},
        )

    def test_requires_bearer_authentication(self):
        response = self.client.post(
            "/api/v1/zabbix/ingest",
            data=ndjson(record("status", 1)),
            content_type="application/x-ndjson",
        )
        self.assertEqual(response.status_code, 401)

    def test_rejects_invalid_content_type_and_ndjson(self):
        response = self.client.post(
            "/api/v1/zabbix/ingest",
            data="{}",
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 415)
        response = self.post("{invalid")
        self.assertEqual(response.status_code, 422)

    def test_accepts_valid_records_from_a_mixed_batch(self):
        response = self.post(ndjson(record("status", 1)) + "\n{invalid-json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accepted"], 1)
        self.assertEqual(response.json()["rejected"], 1)
        self.assertTrue(LatestDataset.objects.get(key="status").payload["reachable"])

    def test_rejects_future_timestamp_without_poisoning_dataset(self):
        future = int(time.time()) + 3600
        response = self.post(ndjson(record("status", 1, future)))
        self.assertEqual(response.status_code, 422)
        self.assertFalse(LatestDataset.objects.exists())

    def test_missing_players_array_does_not_close_session(self):
        clock = int(time.time())
        player = {
            "name": "Explorer",
            "userId": "steam_1",
            "location_x": 1,
            "location_y": 2,
        }
        response = self.post(ndjson(record("players", {"players": [player]}, clock)))
        self.assertEqual(response.status_code, 200)
        response = self.post(
            ndjson(record("players", {"error": "temporary"}, clock + 20))
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(PlayerSession.objects.filter(ended_at__isnull=True).count(), 1)

    def test_ingests_metrics_and_status_batch(self):
        clock = int(time.time())
        metrics = {
            "currentplayernum": 2,
            "maxplayernum": 8,
            "serverfps": 58.5,
            "serverfpsaverage": 59.2,
            "serverframetime": 16.9,
            "days": 5296,
            "basecampnum": 6,
            "uptime": 3600,
        }
        response = self.post(ndjson(record("metrics", metrics, clock), record("status", 1, clock)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accepted"], 2)
        self.assertEqual(MetricSample.objects.count(), 1)
        self.assertEqual(LatestDataset.objects.get(key="metrics").payload["serverfpsaverage"], 59.2)
        self.assertTrue(LatestDataset.objects.get(key="status").payload["reachable"])

    def test_player_data_is_sanitized_and_sessions_are_inferred(self):
        clock = int(time.time())
        raw_player = {
            "name": "Explorer",
            "accountName": "explorer-account",
            "playerId": "RAW-PLAYER-ID",
            "userId": "steam_RAW-USER-ID",
            "ip": "192.0.2.10",
            "ping": 27.4,
            "location_x": -344575.15,
            "location_y": 261830.45,
            "level": 51,
            "building_count": 119,
        }
        response = self.post(ndjson(record("players", {"players": [raw_player]}, clock)))
        self.assertEqual(response.status_code, 200)

        payload = LatestDataset.objects.get(key="players").payload
        serialized = json.dumps(payload)
        self.assertNotIn("192.0.2.10", serialized)
        self.assertNotIn("RAW-PLAYER-ID", serialized)
        self.assertNotIn("RAW-USER-ID", serialized)
        self.assertEqual(payload["players"][0]["name"], "Explorer")
        self.assertEqual(len(payload["players"][0]["id"]), 24)
        self.assertEqual(Player.objects.count(), 1)
        self.assertEqual(PositionSample.objects.count(), 1)
        self.assertEqual(PlayerSession.objects.filter(ended_at__isnull=True).count(), 1)
        self.assertEqual(ServerEvent.objects.filter(event_type="join").count(), 1)

        response = self.post(ndjson(record("players", {"players": []}, clock + 20)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PlayerSession.objects.filter(ended_at__isnull=True).count(), 0)
        self.assertEqual(ServerEvent.objects.filter(event_type="leave").count(), 1)

    def test_ignores_items_not_selected_for_the_site(self):
        unknown = record("unknown", {"secret": "value"})
        unknown["item_tags"] = [{"tag": "integration", "value": "something-else"}]
        response = self.post(ndjson(unknown))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ignored"], 1)
        self.assertFalse(LatestDataset.objects.exists())


class PortSeparationTests(TestCase):
    def test_public_urlconf_does_not_expose_ingest(self):
        response = self.client.post(
            "/api/v1/zabbix/ingest", data="", content_type="application/x-ndjson"
        )
        self.assertEqual(response.status_code, 404)

    @override_settings(ROOT_URLCONF="palworld_site.ingest_urls")
    def test_ingest_urlconf_does_not_expose_dashboard(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 404)
