import json
import time
from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.models import LatestDataset


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
    ZABBIX_SOURCE_HOST="palworld",
    PLAYER_HASH_SECRET="test-player-key",
    SITE_AUTH_REQUIRED=False,
)
class WorldObjectsIngestTests(TestCase):
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

    def world_objects(self):
        with override_settings(ROOT_URLCONF="palworld_site.urls"):
            return self.client.get(reverse("world-objects"))

    def _game_data_payload(self):
        actors = [
            # Player actor (must NOT appear in world objects output).
            {
                "InstanceID": "player-inst-1",
                "TrainerInstanceID": "",
                "userid": "test-user",
                "Type": "player",
                "UnitType": "player",
                "NickName": "TestExplorer",
                "GuildID": "raw-guild-id",
                "GuildName": "Explorers",
                "Class": "",
                "Level": 42,
                "LocationX": -100000,
                "LocationY": 50000,
                "IsActive": "true",
            },
            # Wild Pal (Chillet) at a real Palpagos coordinate.
            {
                "InstanceID": "wild-chillet-1",
                "TrainerInstanceID": "",
                "userid": "",
                "Type": "",
                "UnitType": "wildpal",
                "NickName": "Chillet",
                "GuildID": "",
                "GuildName": "",
                "Class": "BP_Pal地下室_C",
                "Level": 11,
                "LocationX": -315583,
                "LocationY": 237116,
                "IsActive": "true",
            },
            # NPC trader in Palpagos with a class-derived name.
            {
                "InstanceID": "npc-trader-1",
                "TrainerInstanceID": "",
                "userid": "",
                "Type": "",
                "UnitType": "npc",
                "NickName": "",
                "GuildID": "",
                "GuildName": "",
                "Class": "BP_Desert_Trader_C",
                "Level": 0,
                "LocationX": -200000,
                "LocationY": 100000,
                "IsActive": "true",
            },
            # Companion owned by the player actor above (otomopal).
            {
                "InstanceID": "companion-cattiva-1",
                "TrainerInstanceID": "player-inst-1",
                "userid": "",
                "Type": "",
                "UnitType": "otomopal",
                "NickName": "Cattiva",
                "GuildID": "",
                "GuildName": "",
                "Class": "BP_Pal_C",
                "Level": 3,
                "LocationX": -100050,
                "LocationY": 50050,
                "IsActive": "true",
            },
            # Inactive actor that should be filtered out regardless of kind.
            {
                "InstanceID": "wild-lamball-inactive",
                "TrainerInstanceID": "",
                "userid": "",
                "Type": "",
                "UnitType": "wildpal",
                "NickName": "Inactive Lamball",
                "GuildID": "",
                "GuildName": "",
                "Class": "BP_Lamball_C",
                "Level": 5,
                "LocationX": -300000,
                "LocationY": 200000,
                "IsActive": "false",
            },
        ]
        return {"ActorData": actors}

    def test_game_data_is_ingested_and_exposed_via_world_objects_endpoint(self):
        clock = int(time.time())
        response = self.post(
            ndjson(record("game_data", self._game_data_payload(), clock))
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accepted"], 1)

        dataset = LatestDataset.objects.get(key="game_data")
        self.assertEqual(dataset.payload["count"], 3)
        self.assertFalse(dataset.payload["truncated"])

        api_response = self.world_objects()
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()
        self.assertEqual(payload["count"], 3)
        self.assertFalse(payload["stale"])
        self.assertIsNotNone(payload["updated_at"])

        kinds = {obj["kind"] for obj in payload["objects"]}
        self.assertEqual(kinds, {"wild-pals", "npcs", "companions"})
        self.assertNotIn("players", kinds)
        self.assertNotIn("bases", kinds)

        serialized = json.dumps(payload)
        self.assertNotIn("player-inst-1", serialized)
        self.assertNotIn("test-user", serialized)
        self.assertNotIn("raw-guild-id", serialized)
        self.assertNotIn("TrainerInstanceID", serialized)
        self.assertNotIn("InstanceID", serialized)
        self.assertNotIn("userid", serialized)
        self.assertNotIn("GuildID", serialized)
        self.assertNotIn("Inactive Lamball", serialized)

        companion = next(
            obj for obj in payload["objects"] if obj["kind"] == "companions"
        )
        self.assertTrue(companion["owner_id"])
        self.assertEqual(len(companion["owner_id"]), 24)

        for obj in payload["objects"]:
            self.assertIn("map", obj)
            self.assertIn(obj["map"], {"palpagos", "world-tree"})
            self.assertTrue(
                -1100000 <= obj["x"] <= 700000,
                msg=f"x out of bounds: {obj}",
            )
            self.assertTrue(
                -820000 <= obj["y"] <= 730000,
                msg=f"y out of bounds: {obj}",
            )

    def test_world_objects_endpoint_reports_stale_when_dataset_missing(self):
        response = self.world_objects()
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["objects"], [])
        self.assertEqual(payload["count"], 0)
        self.assertTrue(payload["stale"])
        self.assertIsNone(payload["updated_at"])

    def test_world_objects_endpoint_reports_stale_when_data_is_old(self):
        response = self.post(ndjson(record("game_data", self._game_data_payload())))
        self.assertEqual(response.status_code, 200)
        LatestDataset.objects.filter(key="game_data").update(
            source_clock=timezone.now() - timedelta(minutes=30)
        )
        response = self.world_objects()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["stale"])