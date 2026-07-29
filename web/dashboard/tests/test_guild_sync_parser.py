import copy
import importlib.util
import json
from pathlib import Path

from django.test import SimpleTestCase


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "ops"
    / "PalworldGuildSync"
    / "guild_sync.py"
)
SPEC = importlib.util.spec_from_file_location("guild_sync", SCRIPT_PATH)
guild_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guild_sync)


def prop(value):
    return {"value": value}


def enum(value):
    return prop(prop(value))


def character(instance_id, owner_id="", player_uid="", **parameters):
    values = {name: prop(value) for name, value in parameters.items()}
    if owner_id:
        values["OwnerPlayerUId"] = prop(owner_id)
    key = {"InstanceId": prop(instance_id)}
    if player_uid:
        key["PlayerUId"] = prop(player_uid)
    return {
        "key": key,
        "value": {
            "RawData": prop({
                "object": {"SaveParameter": prop(values)},
            }),
        },
    }


class GuildSyncParserTests(SimpleTestCase):
    def setUp(self):
        self.guild_id = "guild-raw-uuid"
        self.player_id = "player-raw-uuid"
        self.base_id = "base-raw-uuid"
        self.container_id = "container-raw-uuid"
        self.world = {
            "GroupSaveDataMap": prop([{
                "key": self.guild_id,
                "value": {
                    "GroupType": enum("EPalGroupType::Guild"),
                    "RawData": prop({
                        "group_id": self.guild_id,
                        "group_name": self.player_id,
                        "guild_name": "Explorers",
                        "admin_player_uid": self.player_id,
                        "players": [{
                            "player_uid": self.player_id,
                            "player_info": {"player_name": "Leader"},
                        }, {
                            "player_uid": "legacy-player-uid",
                            "player_info": {"player_name": "Legacy"},
                        }],
                        "base_ids": [self.base_id],
                    }),
                },
            }]),
            "CharacterSaveParameterMap": prop([
                character(
                    "leader-character",
                    player_uid=self.player_id,
                    IsPlayer=True,
                    NickName="Leader",
                    Level=51,
                    Exp=123456,
                    UnusedStatusPoint=3,
                    GotStatusPointList={
                        "values": [
                            {
                                "StatusName": prop("最大HP"),
                                "StatusPoint": prop(4),
                            },
                            {
                                "StatusName": prop("攻撃力"),
                                "StatusPoint": prop(2),
                            },
                        ],
                    },
                    GotExStatusPointList={
                        "values": [{
                            "StatusName": prop("最大HP"),
                            "StatusPoint": prop(1),
                        }],
                    },
                ),
                character(
                    "healthy-worker",
                    self.player_id,
                    PhysicalHealth=prop("EPalStatusPhysicalHealthType::Healthful"),
                    HungerType=prop("EPalStatusHungerType::Default"),
                    SanityValue=80,
                    CurrentWorkSuitability=prop("EPalWorkSuitability::Mining"),
                ),
                character(
                    "problem-worker",
                    WorkerSick=prop("EPalBaseCampWorkerSickType::Weakness"),
                    HungerType=prop("EPalStatusHungerType::Starvation"),
                    SanityValue=10,
                ),
            ]),
            "CharacterContainerSaveData": prop([{
                "key": {"ID": prop(self.container_id)},
                "value": {
                    "Slots": prop({
                        "values": [
                            {"RawData": prop({"instance_id": "healthy-worker"})},
                            {"RawData": prop({"instance_id": "problem-worker"})},
                            {"RawData": prop(None)},
                        ],
                    }),
                },
            }]),
            "BaseCampSaveData": prop([{
                "key": self.base_id,
                "value": {
                    "RawData": prop({
                        "id": self.base_id,
                        "name": "\u65b0\u898f\u751f\u6210 placeholder",
                        "state": 1,
                        "group_id_belong_to": self.guild_id,
                        "transform": {
                            "translation": {"x": 10, "y": 20, "z": 30},
                        },
                    }),
                    "WorkerDirector": prop({
                        "RawData": prop({"container_id": self.container_id}),
                    }),
                },
            }]),
            "InvaderSaveData": prop([{
                "key": self.base_id,
                "value": {"bIsInvading": prop(True)},
            }]),
            "OilrigSaveData": prop({
                "OilrigMap": prop([
                    {
                        "key": "EPalOilrigType::TypeA",
                        "value": {"Alarm": prop(True), "Clear": prop(False)},
                    },
                    {
                        "key": "EPalOilrigType::Debug",
                        "value": {"Alarm": prop(True), "Clear": prop(True)},
                    },
                ]),
            }),
            "GameTimeSaveData": prop({"GameDateTimeTicks": prop(123)}),
        }

    def test_builds_compact_health_and_world_aggregates(self):
        guild_sync.validate_world_data(self.world)
        guilds = guild_sync.parse_guilds(self.world)
        players = guild_sync.parse_players(self.world, guilds)
        characters, guild_pal_ids = guild_sync.index_characters(self.world, guilds)
        containers = guild_sync.index_character_containers(self.world)
        world, raid_ids = guild_sync.parse_world(self.world)
        bases, diagnostics, workers, working, problems = guild_sync.parse_bases(
            self.world,
            guilds,
            characters,
            containers,
            guild_pal_ids,
            raid_ids,
        )
        guild_sync.enrich_guilds(
            guilds, bases, guild_pal_ids, workers, working, problems
        )

        self.assertEqual(bases[0]["name"], "Base 1")
        self.assertEqual(bases[0]["worker_count"], 2)
        self.assertEqual(bases[0]["working_count"], 1)
        self.assertEqual(bases[0]["sick_count"], 1)
        self.assertEqual(bases[0]["hungry_count"], 1)
        self.assertEqual(bases[0]["low_sanity_count"], 1)
        self.assertEqual(bases[0]["problem_worker_count"], 1)
        self.assertTrue(bases[0]["raid_active"])
        self.assertEqual(guilds[0]["pal_count"], 2)
        self.assertEqual(guilds[0]["problem_worker_count"], 1)
        self.assertEqual(world["active_raid_count"], 1)
        self.assertEqual(world["oil_rig_count"], 1)
        self.assertEqual(world["oil_rig_alert_count"], 1)
        self.assertEqual(diagnostics["unresolved_worker_count"], 0)

        public_guilds, public_bases, public_players = guild_sync.minimize_payload(
            guilds, bases, players
        )
        serialized = json.dumps([public_guilds, public_bases, public_players])
        self.assertNotIn(self.guild_id, serialized)
        self.assertNotIn(self.player_id, serialized)
        self.assertNotIn(self.base_id, serialized)
        self.assertEqual(len(public_guilds[0]["group_id"]), 20)
        self.assertTrue(public_guilds[0]["players"][0]["is_admin"])
        self.assertNotIn("group_name", public_guilds[0])
        self.assertNotIn("location_z", public_bases[0])
        self.assertNotIn("player_count", public_bases[0])
        leader = next(
            player for player in public_players if player["player_name"] == "Leader"
        )
        legacy = next(
            player for player in public_players if player["player_name"] == "Legacy"
        )
        self.assertEqual(len(leader["player_id"]), 20)
        self.assertEqual(leader["level"], 51)
        self.assertEqual(leader["exp"], 123456)
        self.assertEqual(leader["owned_pal_count"], 1)
        self.assertEqual(leader["unused_status_points"], 3)
        self.assertEqual(leader["status_points"], {"max_hp": 5, "attack": 2})
        self.assertEqual(legacy["level"], 0)
        self.assertEqual(legacy["owned_pal_count"], 0)

    def test_rejects_an_unsupported_core_dataset(self):
        self.world["CharacterSaveParameterMap"] = prop({})
        with self.assertRaisesRegex(ValueError, "CharacterSaveParameterMap"):
            guild_sync.validate_world_data(self.world)

    def test_rejects_empty_or_undecoded_core_data(self):
        empty_groups = copy.deepcopy(self.world)
        empty_groups["GroupSaveDataMap"] = prop([])

        undecoded_groups = copy.deepcopy(self.world)
        undecoded_groups["GroupSaveDataMap"]["value"][0]["value"]["RawData"] = prop({
            "values": [1, 2, 3],
        })

        undecoded_characters = copy.deepcopy(self.world)
        undecoded_characters["CharacterSaveParameterMap"]["value"][0]["value"][
            "RawData"
        ] = prop({"values": [1, 2, 3]})

        undecoded_bases = copy.deepcopy(self.world)
        undecoded_bases["BaseCampSaveData"]["value"][0]["value"]["RawData"] = prop({
            "values": [1, 2, 3],
        })

        undecoded_containers = copy.deepcopy(self.world)
        undecoded_containers["CharacterContainerSaveData"]["value"][0]["value"][
            "Slots"
        ] = prop({"values": [{"RawData": prop({"values": [1, 2, 3]})}]})

        cases = (
            ("GroupSaveDataMap", empty_groups),
            ("GroupSaveDataMap", undecoded_groups),
            ("CharacterSaveParameterMap", undecoded_characters),
            ("BaseCampSaveData", undecoded_bases),
            ("CharacterContainerSaveData", undecoded_containers),
        )
        for dataset, world in cases:
            with self.subTest(dataset=dataset):
                with self.assertRaisesRegex(ValueError, dataset):
                    guild_sync.validate_world_data(world)

    def test_does_not_fall_back_to_the_technical_group_name(self):
        raw_data = self.world["GroupSaveDataMap"]["value"][0]["value"]["RawData"][
            "value"
        ]
        raw_data.pop("guild_name")
        guilds = guild_sync.parse_guilds(self.world)
        public_guilds, _, _ = guild_sync.minimize_payload(guilds, [], [])

        self.assertEqual(public_guilds[0]["guild_name"], "")
        self.assertNotIn(self.player_id, json.dumps(public_guilds))
