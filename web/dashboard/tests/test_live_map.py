import json
from collections import Counter
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.models import (
    GuildSnapshot,
    LatestDataset,
    Player,
    PositionSample,
)


@override_settings(SITE_AUTH_REQUIRED=False)
class LiveMapTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def test_page_uses_the_shared_spa_shell(self):
        response = self.client.get(reverse("map"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/app.html")
        self.assertContains(response, 'id="root"')
        self.assertContains(response, "dashboard/live-map/live-map.css")
        self.assertContains(response, "dashboard/live-map/live-map.js")
        self.assertNotContains(response, "dashboard/js/site.js")
        self.assertNotContains(response, "mapViewport")

    def test_config_uses_versioned_catalogue_and_original_map_assets(self):
        response = self.client.get(reverse("live-map-config"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["pollIntervalMs"], 20000)
        self.assertEqual(payload["worldPollIntervalMs"], 15000)
        self.assertTrue(payload["worldDataEnabled"])
        self.assertEqual(
            [layer["id"] for layer in payload["layers"]],
            ["palpagos", "world-tree"],
        )
        self.assertIn("palpagos.jpg", payload["layers"][0]["imageUrl"])
        self.assertIn("world-tree.jpg", payload["layers"][1]["imageUrl"])
        self.assertEqual(
            payload["catalogueUrl"],
            f"{reverse('live-map-catalogue')}?v="
            "be868d37d96bdfc133f4e8a2a59e973002d51c0c3d48661dfaaf6e71be7d31f8",
        )
        self.assertEqual(
            payload["upstreamRevision"],
            "711ededa62e6fbf9301a68e1d9e093af4c4210f6",
        )
        self.assertEqual(payload["landmarkCatalogue"]["gameVersion"], "1.0.3.101283")
        self.assertEqual(
            payload["landmarkCatalogue"]["decoder"],
            "CUE4Parse/1.2.2.202608",
        )
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])

    def test_catalogue_is_complete_minimized_and_immutable_when_versioned(self):
        config = self.client.get(reverse("live-map-config")).json()
        response = self.client.get(config["catalogueUrl"])

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["gameVersion"], "1.0.3.101283")
        self.assertEqual(payload["decoder"], "CUE4Parse/1.2.2.202608")
        self.assertEqual(len(payload["locations"]), 1146)
        self.assertEqual(
            Counter(item["map"] for item in payload["locations"]),
            {"palpagos": 1064, "world-tree": 82},
        )
        self.assertEqual(
            Counter(item["kind"] for item in payload["locations"]),
            {
                "alpha-pals": 90,
                "bosses": 9,
                "bounties": 33,
                "oil-rigs": 3,
                "dungeon-entrances": 170,
                "watchtowers": 22,
                "waypoints": 152,
                "ancient-shrine-pickups": 106,
                "effigies": 407,
                "journals": 64,
                "npc-locations": 90,
            },
        )
        allowed = {"id", "kind", "name", "detail", "level", "x", "y", "map"}
        self.assertTrue(
            all(set(location) <= allowed for location in payload["locations"])
        )
        self.assertIn(
            {
                "name": "Zenara & Astralym",
                "detail": "Sealed Sanctum",
            },
            [
                {key: location[key] for key in ("name", "detail")}
                for location in payload["locations"]
                if location["name"] == "Zenara & Astralym"
            ],
        )
        serialized = response.content.decode()
        for forbidden in (
            "InstanceID",
            "TrainerInstanceID",
            "GuildID",
            "sourceObject",
            "className",
            "gameId",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertIn("immutable", response.headers["Cache-Control"])
        self.assertEqual(
            response.headers["ETag"],
            '"be868d37d96bdfc133f4e8a2a59e973002d51c0c3d48661dfaaf6e71be7d31f8"',
        )
        not_modified = self.client.get(
            config["catalogueUrl"],
            HTTP_IF_NONE_MATCH=response.headers["ETag"],
        )
        self.assertEqual(not_modified.status_code, 304)

    def test_players_adapter_merges_public_live_save_and_guild_data(self):
        LatestDataset.objects.create(
            key="status", payload={"reachable": True}, source_clock=self.now
        )
        LatestDataset.objects.create(
            key="info",
            payload={
                "servername": "Test Palworld",
                "description": "Private server",
                "version": "1.0.1.100619",
            },
            source_clock=self.now,
        )
        LatestDataset.objects.create(
            key="metrics",
            payload={
                "currentplayernum": 1,
                "maxplayernum": 8,
                "serverfps": 59,
                "serverframetime": 16.9,
                "uptime": 3600,
                "basecampnum": 1,
                "days": 42,
            },
            source_clock=self.now,
        )
        LatestDataset.objects.create(
            key="players",
            payload={
                "players": [
                    {
                        "id": "public-player-id",
                        "name": "Explorer",
                        "level": 50,
                        "location_x": -100,
                        "location_y": 200,
                    }
                ]
            },
            source_clock=self.now,
        )
        LatestDataset.objects.create(
            key="game_data",
            payload={
                "objects": [
                    {
                        "id": "public-base-id",
                        "kind": "bases",
                        "name": "Explorers",
                        "guild_name": "Explorers",
                        "guild_key": "d" * 24,
                        "x": -120,
                        "y": 210,
                        "map": "palpagos",
                    }
                ]
            },
            source_clock=self.now,
        )
        player = Player.objects.create(
            public_id="public-player-id",
            name="Explorer",
            first_seen=self.now - timedelta(days=2),
            last_seen=self.now,
            level=50,
        )
        PositionSample.objects.create(
            player=player,
            source_clock=self.now,
            x=-100,
            y=200,
            level=50,
        )
        GuildSnapshot.objects.create(
            payload={
                "schema_version": 3,
                "guilds": [
                    {
                        "group_id": "a" * 20,
                        "guild_name": "Explorers",
                        "players": [],
                    }
                ],
                "bases": [],
                "players": [
                    {
                        "player_id": "b" * 20,
                        "player_name": "Explorer",
                        "guild_id": "a" * 20,
                        "level": 55,
                    }
                ],
            }
        )

        with self.assertNumQueries(3):
            response = self.client.get(reverse("live-map-players"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["connected"])
        self.assertFalse(payload["stale"])
        self.assertEqual(payload["server"]["name"], "Test Palworld")
        self.assertEqual(payload["metrics"]["serverFps"], 59)
        self.assertEqual(len(payload["players"]), 1)
        public_player = payload["players"][0]
        self.assertEqual(public_player["id"], "public-player-id")
        self.assertEqual(public_player["level"], 55)
        self.assertTrue(public_player["online"])
        self.assertEqual(public_player["guildKey"], "d" * 24)
        self.assertEqual(public_player["guildName"], "Explorers")
        self.assertEqual(public_player["map"], "palpagos")
        serialized = json.dumps(payload)
        self.assertNotIn("player_id", serialized)
        self.assertNotIn("group_id", serialized)

    def test_stale_player_data_keeps_last_position_but_marks_player_offline(self):
        stale_time = self.now - timedelta(minutes=10)
        LatestDataset.objects.create(
            key="status", payload={"reachable": True}, source_clock=self.now
        )
        LatestDataset.objects.create(
            key="players",
            payload={
                "players": [
                    {
                        "id": "public-player-id",
                        "name": "Explorer",
                        "level": 10,
                        "location_x": -100,
                        "location_y": 200,
                    }
                ]
            },
            source_clock=stale_time,
        )
        player = Player.objects.create(
            public_id="public-player-id",
            name="Explorer",
            first_seen=stale_time,
            last_seen=stale_time,
            level=10,
        )
        PositionSample.objects.create(
            player=player,
            source_clock=stale_time,
            x=-100,
            y=200,
        )

        payload = self.client.get(reverse("live-map-players")).json()

        self.assertTrue(payload["stale"])
        self.assertFalse(payload["connected"])
        self.assertFalse(payload["players"][0]["online"])

    def test_fresh_player_without_live_coordinates_is_not_shown_at_old_position(self):
        LatestDataset.objects.create(
            key="status", payload={"reachable": True}, source_clock=self.now
        )
        LatestDataset.objects.create(
            key="players",
            payload={
                "players": [
                    {
                        "id": "public-player-id",
                        "name": "Explorer",
                        "level": 10,
                        "location_x": 0,
                        "location_y": 0,
                    }
                ]
            },
            source_clock=self.now,
        )
        player = Player.objects.create(
            public_id="public-player-id",
            name="Explorer",
            first_seen=self.now - timedelta(days=1),
            last_seen=self.now,
            level=10,
        )
        PositionSample.objects.create(
            player=player,
            source_clock=self.now - timedelta(minutes=1),
            x=-100,
            y=200,
        )

        payload = self.client.get(reverse("live-map-players")).json()

        self.assertTrue(payload["connected"])
        self.assertEqual(payload["players"], [])

    def test_newer_player_snapshot_supersedes_an_older_failed_status_check(self):
        LatestDataset.objects.create(
            key="status",
            payload={"reachable": False},
            source_clock=self.now - timedelta(seconds=1),
        )
        LatestDataset.objects.create(
            key="players",
            payload={"players": []},
            source_clock=self.now,
        )

        payload = self.client.get(reverse("live-map-players")).json()

        self.assertTrue(payload["connected"])
        self.assertFalse(payload["stale"])

    def test_object_adapter_uses_camel_case_public_relations(self):
        LatestDataset.objects.create(
            key="game_data",
            payload={
                "supported_count": 2,
                "truncated": False,
                "objects": [
                    {
                        "id": "public-base-id",
                        "kind": "bases",
                        "name": "Explorers",
                        "base_id": "public-base-id",
                        "guild_key": "c" * 24,
                        "guild_name": "Explorers",
                        "x": -100,
                        "y": 200,
                        "map": "palpagos",
                    },
                    {
                        "id": "public-worker-id",
                        "kind": "workers",
                        "name": "Anubis",
                        "base_id": "public-base-id",
                        "guild_key": "c" * 24,
                        "level": 44,
                        "x": -110,
                        "y": 210,
                        "map": "palpagos",
                    },
                ],
            },
            source_clock=self.now,
        )

        response = self.client.get(reverse("live-map-objects"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["enabled"])
        self.assertTrue(payload["available"])
        self.assertFalse(payload["stale"])
        self.assertEqual(payload["total"], 2)
        worker = payload["objects"][1]
        self.assertEqual(worker["baseId"], "public-base-id")
        self.assertEqual(worker["guildKey"], "c" * 24)
        self.assertNotIn("base_id", worker)
        self.assertNotIn("guild_key", worker)

    def test_companion_adapter_selects_the_owner_candidate_known_to_django(self):
        Player.objects.create(
            public_id="matching-public-player",
            name="Explorer",
            first_seen=self.now,
            last_seen=self.now,
        )
        LatestDataset.objects.create(
            key="game_data",
            payload={
                "objects": [
                    {
                        "id": "public-companion-id",
                        "kind": "companions",
                        "name": "Cattiva",
                        "owner_id": "non-matching-candidate",
                        "owner_ids": [
                            "non-matching-candidate",
                            "matching-public-player",
                        ],
                        "x": -100,
                        "y": 200,
                        "map": "palpagos",
                    }
                ]
            },
            source_clock=self.now,
        )

        payload = self.client.get(reverse("live-map-objects")).json()

        self.assertEqual(
            payload["objects"][0]["ownerId"], "matching-public-player"
        )
        self.assertNotIn("owner_ids", payload["objects"][0])
