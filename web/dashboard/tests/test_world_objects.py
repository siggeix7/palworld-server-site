import base64
import json
import time
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.models import LatestDataset
from dashboard.services import (
    _GAME_DATA_CHUNKS,
    _player_id,
    _player_id_from_instance,
    _reset_game_data_chunks,
)


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


def chunk_record(index, raw_value, clock):
    value = base64.b64encode(raw_value).decode("ascii")
    result = record("game_data_chunk", value, clock, name=f"Game Data Chunk {index}")
    result["item_tags"].append({"tag": "chunk", "value": str(index)})
    result["type"] = 5
    return result


def chunk_records(payload, clock):
    raw_value = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return [
        chunk_record(
            index,
            raw_value[len(raw_value) * index // 12:len(raw_value) * (index + 1) // 12],
            clock,
        )
        for index in range(12)
    ]


@override_settings(
    ROOT_URLCONF="palworld_site.ingest_urls",
    ZABBIX_CONNECTOR_TOKEN="test-connector-token",
    ZABBIX_SOURCE_HOST="palworld",
    PLAYER_HASH_SECRET="test-player-key",
    SITE_AUTH_REQUIRED=False,
)
class WorldObjectsIngestTests(TestCase):
    def setUp(self):
        _reset_game_data_chunks()
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
        player_instance = "a" * 32 + ":" + "b" * 32
        actors = [
            # Player actor (must NOT appear in world objects output).
            {
                "InstanceID": player_instance.upper(),
                "TrainerInstanceID": "",
                "userid": "test-user",
                "Type": "Character",
                "UnitType": "Player",
                "NickName": "TestExplorer",
                "GuildID": "raw-guild-id",
                "GuildName": "Explorers",
                "Class": "",
                "level": 42,
                "LocationX": -100000,
                "LocationY": 50000,
                "IsActive": "",
            },
            # PalBox records can omit both IsActive and InstanceID.
            {
                "Type": "PalBox",
                "UnitType": "",
                "GuildID": "raw-guild-id",
                "GuildName": "Explorers",
                "Class": "BP_PalBoxV2_C",
                "LocationX": -100000,
                "LocationY": 50000,
            },
            # Base worker with the lowercase level field used by game-data.
            {
                "InstanceID": "worker-anubis-1",
                "Type": "Character",
                "UnitType": "BaseCampPal",
                "NickName": "Anubis",
                "GuildID": "RAW-GUILD-ID",
                "GuildName": "Explorers",
                "Class": "BP_Anubis_C",
                "level": 44,
                "LocationX": -100100,
                "LocationY": 50100,
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
                "level": 11,
                "LocationX": -315583,
                "LocationY": 237116,
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
                "level": 0,
                "LocationX": -200000,
                "LocationY": 100000,
            },
            # Companion owned by the player actor above (otomopal).
            {
                "InstanceID": "companion-cattiva-1",
                "TrainerInstanceID": player_instance.lower(),
                "userid": "",
                "Type": "",
                "UnitType": "otomopal",
                "NickName": "Cattiva",
                "GuildID": "",
                "GuildName": "",
                "Class": "BP_Pal_C",
                "level": 3,
                "LocationX": -100050,
                "LocationY": 50050,
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
                "level": 5,
                "LocationX": -300000,
                "LocationY": 200000,
                "IsActive": "false",
            },
            # Missing coordinates must not silently become (0, 0).
            {
                "InstanceID": "npc-without-y",
                "Type": "Character",
                "UnitType": "NPC",
                "NickName": "Incomplete",
                "LocationX": 10,
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
        self.assertEqual(dataset.payload["count"], 5)
        self.assertEqual(dataset.payload["source_count"], 8)
        self.assertEqual(dataset.payload["kind_counts"], {
            "bases": 1,
            "workers": 1,
            "companions": 1,
            "npcs": 1,
            "wild-pals": 1,
        })
        self.assertEqual(dataset.payload["omitted_counts"]["inactive"], 1)
        self.assertEqual(dataset.payload["omitted_counts"]["invalid_coordinates"], 1)
        self.assertFalse(dataset.payload["truncated"])

        api_response = self.world_objects()
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.json()
        self.assertTrue(payload["available"])
        self.assertEqual(payload["count"], 5)
        self.assertEqual(payload["source_count"], 8)
        self.assertFalse(payload["stale"])
        self.assertIsNotNone(payload["updated_at"])

        kinds = {obj["kind"] for obj in payload["objects"]}
        self.assertEqual(kinds, {"bases", "workers", "wild-pals", "npcs", "companions"})
        self.assertNotIn("players", kinds)

        serialized = json.dumps(payload)
        self.assertNotIn("a" * 32, serialized)
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
        base = next(obj for obj in payload["objects"] if obj["kind"] == "bases")
        worker = next(obj for obj in payload["objects"] if obj["kind"] == "workers")
        self.assertEqual(base["base_id"], base["id"])
        self.assertEqual(worker["base_id"], base["id"])
        self.assertEqual(worker["guild_key"], base["guild_key"])
        self.assertEqual(worker["level"], 44)

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
        self.assertFalse(payload["available"])
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

    def test_world_tree_overlap_prefers_world_tree_layer(self):
        payload = {"ActorData": [{
            "InstanceID": "world-tree-npc",
            "Type": "Character",
            "UnitType": "NPC",
            "NickName": "World Tree NPC",
            "LocationX": 348000,
            "LocationY": -600000,
        }]}
        response = self.post(ndjson(record("game_data", payload)))
        self.assertEqual(response.status_code, 200)
        obj = LatestDataset.objects.get(key="game_data").payload["objects"][0]
        self.assertEqual(obj["map"], "world-tree")

    def test_ambiguous_identities_are_omitted(self):
        payload = {"ActorData": [
            {
                "InstanceID": "duplicate",
                "Type": "Character",
                "UnitType": "NPC",
                "NickName": "One",
                "LocationX": 1,
                "LocationY": 2,
            },
            {
                "InstanceID": "DUPLICATE",
                "Type": "Character",
                "UnitType": "NPC",
                "NickName": "Two",
                "LocationX": 3,
                "LocationY": 4,
            },
            {
                "InstanceID": "unique",
                "Type": "Character",
                "UnitType": "NPC",
                "NickName": "Merchant",
                "LocationX": 5,
                "LocationY": 6,
            },
        ]}
        response = self.post(ndjson(record("game_data", payload)))
        self.assertEqual(response.status_code, 200)
        stored = LatestDataset.objects.get(key="game_data").payload
        self.assertEqual(stored["count"], 1)
        self.assertEqual(stored["objects"][0]["name"], "Merchant")
        self.assertEqual(stored["omitted_counts"]["ambiguous_identity"], 2)

    def test_object_limit_keeps_higher_priority_kinds(self):
        payload = {"ActorData": [
            {
                "InstanceID": "wild-1",
                "Type": "Character",
                "UnitType": "WildPal",
                "NickName": "Wild",
                "LocationX": 1,
                "LocationY": 2,
            },
            {
                "InstanceID": "npc-1",
                "Type": "Character",
                "UnitType": "NPC",
                "NickName": "NPC",
                "LocationX": 3,
                "LocationY": 4,
            },
            {
                "Type": "PalBox",
                "GuildID": "guild",
                "GuildName": "Priority base",
                "LocationX": 5,
                "LocationY": 6,
            },
        ]}
        with patch("dashboard.services.MAX_WORLD_OBJECTS", 2):
            response = self.post(ndjson(record("game_data", payload)))
        self.assertEqual(response.status_code, 200)
        stored = LatestDataset.objects.get(key="game_data").payload
        self.assertTrue(stored["truncated"])
        self.assertEqual(stored["supported_count"], 3)
        self.assertEqual(
            [obj["kind"] for obj in stored["objects"]],
            ["bases", "npcs"],
        )

    def test_binary_chunks_reassemble_in_memory_across_connector_batches(self):
        clock = int(time.time())
        player_instance = "a" * 32 + ":" + "b" * 32
        actors = [
            {
                "InstanceID": player_instance,
                "userid": "private-user",
                "Type": "Character",
                "UnitType": "Player",
            },
            {
                "Type": "PalBox",
                "GuildID": "private-guild",
                "GuildName": "Chunk Guild",
                "LocationX": -100000,
                "LocationY": 50000,
            },
            {
                "InstanceID": "private-worker",
                "Type": "Character",
                "UnitType": "BaseCampPal",
                "GuildID": "private-guild",
                "NickName": "Chunk W\u00f6rker",
                "LocationX": -100100,
                "LocationY": 50100,
            },
            {
                "InstanceID": "private-companion",
                "TrainerInstanceID": player_instance,
                "Type": "Character",
                "UnitType": "OtomoPal",
                "GuildID": "private-guild",
                "NickName": "Chunk Companion",
                "LocationX": -200000,
                "LocationY": 100000,
            },
            {
                "InstanceID": "private-wild",
                "Type": "Character",
                "UnitType": "WildPal",
                "NickName": "Chunk Wild",
                "LocationX": -300000,
                "LocationY": 200000,
            },
            {
                "InstanceID": "private-npc",
                "Type": "Character",
                "UnitType": "NPC",
                "NickName": "Chunk NPC",
                "LocationX": -400000,
                "LocationY": 300000,
            },
        ]
        chunks = chunk_records({"ActorData": actors}, clock)
        first = self.post(ndjson(*[
            chunks[index]
            for index in range(6)
        ]))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["accepted"], 6)
        self.assertFalse(LatestDataset.objects.filter(key="game_data").exists())

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            second = self.post(ndjson(*[
                chunks[index]
                for index in range(11, 5, -1)
            ]))
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["accepted"], 6)
        self.assertIn("game_data", second.json()["datasets"])
        self.assertTrue(_GAME_DATA_CHUNKS)
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        self.assertFalse(_GAME_DATA_CHUNKS)
        payload = LatestDataset.objects.get(key="game_data").payload
        self.assertEqual(payload["source_count"], 6)
        self.assertEqual(payload["count"], 5)
        self.assertEqual(payload["kind_counts"], {
            "bases": 1,
            "workers": 1,
            "companions": 1,
            "npcs": 1,
            "wild-pals": 1,
        })
        serialized = json.dumps(payload)
        for private_value in (
            "private-user",
            "private-guild",
            "private-worker",
            "private-companion",
            "private-wild",
            "private-npc",
        ):
            self.assertNotIn(private_value, serialized)

    def test_binary_chunks_keep_newest_clocks_in_item_major_backlog(self):
        clocks = [int(time.time()) + offset for offset in range(3)]
        snapshots = {
            clock: chunk_records({"ActorData": [{
                "InstanceID": f"npc-{clock}",
                "Type": "Character",
                "UnitType": "NPC",
                "NickName": f"Snapshot {clock}",
                "LocationX": 1,
                "LocationY": 2,
            }]}, clock)
            for clock in clocks
        }
        item_major_records = [
            snapshots[clock][chunk_index]
            for chunk_index in range(12)
            for clock in clocks
        ]

        for offset in range(0, len(item_major_records), 3):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post(ndjson(*item_major_records[offset:offset + 3]))
            self.assertEqual(response.status_code, 200)

        stored = LatestDataset.objects.get(key="game_data")
        self.assertEqual(stored.source_clock, timezone.datetime.fromtimestamp(
            clocks[-1],
            tz=timezone.get_current_timezone(),
        ))
        self.assertEqual(
            stored.payload["objects"][0]["name"],
            f"Snapshot {clocks[-1]}",
        )
        self.assertFalse(_GAME_DATA_CHUNKS)

    def test_binary_chunk_rejects_invalid_base64(self):
        value_record = record("game_data_chunk", "not-base64!", int(time.time()))
        value_record["item_tags"].append({"tag": "chunk", "value": "0"})
        value_record["type"] = 5
        response = self.post(ndjson(value_record))
        self.assertEqual(response.status_code, 422)
        self.assertIn("not valid Base64", response.json()["error"])

    def test_incomplete_binary_chunks_expire_from_memory(self):
        with patch("dashboard.services.GAME_DATA_CHUNK_TTL_SECONDS", 0.02):
            chunks = chunk_records(
                {"ActorData": [{"InstanceID": "temporary"}]},
                int(time.time()),
            )
            response = self.post(ndjson(chunks[0]))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(_GAME_DATA_CHUNKS)
            time.sleep(0.08)
            self.assertFalse(_GAME_DATA_CHUNKS)

    def test_duplicate_user_ids_fall_back_to_unique_player_ids(self):
        player_one = "1" * 32
        player_two = "2" * 32
        actor_one = player_one + ":" + "a" * 32
        actor_two = player_two + ":" + "b" * 32
        game_data = {"ActorData": [
            {
                "InstanceID": actor_one,
                "userid": "shared-user",
                "Type": "Character",
                "UnitType": "Player",
            },
            {
                "InstanceID": actor_two,
                "userid": "shared-user",
                "Type": "Character",
                "UnitType": "Player",
            },
            {
                "InstanceID": "companion-one",
                "TrainerInstanceID": actor_one,
                "Type": "Character",
                "UnitType": "OtomoPal",
                "NickName": "Owned Pal",
                "LocationX": 1,
                "LocationY": 2,
            },
        ]}
        players = {"players": [
            {
                "playerId": player_one,
                "userId": "shared-user",
                "name": "One",
                "location_x": 1,
                "location_y": 2,
                "level": 1,
            },
            {
                "playerId": player_two,
                "userId": "shared-user",
                "name": "Two",
                "location_x": 3,
                "location_y": 4,
                "level": 1,
            },
        ]}
        response = self.post(ndjson(
            record("game_data", game_data),
            record("players", players),
        ))
        self.assertEqual(response.status_code, 200)
        companion = LatestDataset.objects.get(key="game_data").payload["objects"][0]
        public_players = LatestDataset.objects.get(key="players").payload["players"]
        self.assertEqual(len({player["id"] for player in public_players}), 2)
        self.assertIn(companion["owner_id"], {player["id"] for player in public_players})

    def test_player_public_id_keeps_legacy_raw_hmac_identity(self):
        raw_player = {
            "userId": "Mixed-Case-User",
            "playerId": "A" * 32,
            "name": "Legacy Player",
            "location_x": 1,
            "location_y": 2,
            "level": 1,
        }
        response = self.post(ndjson(record("players", {"players": [raw_player]})))
        self.assertEqual(response.status_code, 200)
        stored_player = LatestDataset.objects.get(key="players").payload["players"][0]
        self.assertEqual(stored_player["id"], _player_id(raw_player))

    def test_player_id_parser_accepts_spaces_around_instance_separator(self):
        player_id = "a" * 32
        actor_id = "b" * 32
        self.assertEqual(
            _player_id_from_instance(f" {player_id} : {actor_id} "),
            player_id,
        )

    def test_companion_owner_candidates_cover_player_id_only_payload(self):
        player_id = "A" * 32
        actor_instance = player_id + ":" + "B" * 32
        game_data = {"ActorData": [
            {
                "InstanceID": actor_instance,
                "userid": "game-data-user",
                "Type": "Character",
                "UnitType": "Player",
            },
            {
                "InstanceID": "companion-player-id-fallback",
                "TrainerInstanceID": actor_instance,
                "Type": "Character",
                "UnitType": "OtomoPal",
                "NickName": "Fallback Pal",
                "LocationX": 1,
                "LocationY": 2,
            },
        ]}
        players = {"players": [{
            "playerId": player_id,
            "name": "Player ID Only",
            "location_x": 1,
            "location_y": 2,
            "level": 1,
        }]}
        response = self.post(ndjson(
            record("game_data", game_data),
            record("players", players),
        ))
        self.assertEqual(response.status_code, 200)
        companion = LatestDataset.objects.get(key="game_data").payload["objects"][0]
        public_player = LatestDataset.objects.get(key="players").payload["players"][0]
        self.assertIn(public_player["id"], companion["owner_ids"])
