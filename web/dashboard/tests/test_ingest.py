import json
import time
from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from dashboard.models import (
    ConnectorBatch,
    GuildSnapshot,
    LatestDataset,
    MetricSample,
    Player,
    PlayerSession,
    PositionSample,
    ServerEvent,
    VmMetricSample,
)
from palworld_site import ingest_settings


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


def vm_record(metric, value, value_type=0, clock=None):
    value_record = record("vm", value, clock, name=f"Site VM: {metric}")
    value_record["item_tags"].append({"tag": "metric", "value": metric})
    value_record["type"] = value_type
    return value_record


@override_settings(
    ROOT_URLCONF="palworld_site.ingest_urls",
    ZABBIX_CONNECTOR_TOKEN="test-connector-token",
    ZABBIX_SOURCE_HOST="palworld",
    PLAYER_HASH_SECRET="test-player-secret",
    SITE_AUTH_REQUIRED=False,
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

    def test_non_ascii_bearer_token_is_rejected_without_server_error(self):
        response = self.client.post(
            "/api/v1/zabbix/ingest",
            data=ndjson(record("status", 1)),
            content_type="application/x-ndjson",
            HTTP_AUTHORIZATION="Bearer tåken",
        )
        self.assertEqual(response.status_code, 401)

    def test_guild_ingest_stores_guilds_and_bases(self):
        payload = {
            "schema_version": 2,
            "guilds": [{
                "group_id": "aaaaaaaaaaaaaaaaaaaa",
                "guild_name": "Explorers",
                "pal_count": 24,
                "worker_count": 8,
                "working_count": 6,
                "problem_worker_count": 1,
                "players": [],
            }],
            "bases": [
                {
                    "base_id": "bbbbbbbbbbbbbbbbbbbb",
                    "group_id": "aaaaaaaaaaaaaaaaaaaa",
                    "name": "Forte Nord",
                    "location_x": -100,
                    "location_y": 200,
                    "worker_count": 8,
                    "problem_worker_count": 1,
                    "work_types": [],
                    "raid_active": False,
                }
            ],
            "world": {"active_raid_count": 0, "oil_rig_count": 3},
            "diagnostics": {"unresolved_worker_count": 0},
        }
        response = self.client.post(
            "/api/v1/guild/ingest",
            data=json.dumps(payload),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(GuildSnapshot.objects.get(pk=1).payload, payload)

    def test_guild_ingest_stores_minimized_saved_players(self):
        payload = {
            "schema_version": 3,
            "guilds": [{
                "group_id": "aaaaaaaaaaaaaaaaaaaa",
                "guild_name": "Explorers",
                "players": [],
            }],
            "bases": [],
            "players": [{
                "player_id": "cccccccccccccccccccc",
                "player_name": "Historical Explorer",
                "guild_id": "aaaaaaaaaaaaaaaaaaaa",
                "is_admin": False,
                "level": 42,
                "exp": 987654,
                "owned_pal_count": 17,
                "unused_status_points": 2,
                "status_points": {"max_hp": 5, "attack": 3},
            }],
            "world": {},
            "diagnostics": {},
        }
        response = self.client.post(
            "/api/v1/guild/ingest",
            data=json.dumps(payload),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(GuildSnapshot.objects.get(pk=1).payload, payload)

        payload["players"][0]["player_uid"] = "raw-player-uuid"
        response = self.client.post(
            "/api/v1/guild/ingest",
            data=json.dumps(payload),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_guild_ingest_requires_json_object_with_arrays(self):
        response = self.client.post(
            "/api/v1/guild/ingest",
            data="{}",
            content_type="text/plain",
            **self.headers,
        )
        self.assertEqual(response.status_code, 415)

        response = self.client.post(
            "/api/v1/guild/ingest",
            data=json.dumps({"guilds": {}, "bases": []}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(GuildSnapshot.objects.exists())

    def test_guild_ingest_rejects_malformed_entries_and_unicode_token(self):
        response = self.client.post(
            "/api/v1/guild/ingest",
            data=json.dumps({
                "schema_version": 2,
                "guilds": [None],
                "bases": [],
                "world": {},
                "diagnostics": {},
            }),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.post(
            "/api/v1/guild/ingest",
            data=json.dumps({
                "schema_version": 2,
                "guilds": [{
                    "group_id": "raw-guild-uuid",
                    "guild_name": "Explorers",
                    "players": [],
                }],
                "bases": [],
                "world": {},
                "diagnostics": {},
            }),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.post(
            "/api/v1/guild/ingest",
            data=json.dumps({
                "schema_version": 2,
                "guilds": [],
                "bases": [],
                "world": {},
                "diagnostics": {},
            }),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer tåken",
        )
        self.assertEqual(response.status_code, 401)

    @override_settings(ZABBIX_CONNECTOR_TOKEN="")
    def test_guild_ingest_rejects_when_token_is_not_configured(self):
        response = self.client.post(
            "/api/v1/guild/ingest",
            data=json.dumps({"guilds": [], "bases": []}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer test-connector-token",
        )
        self.assertEqual(response.status_code, 503)

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

    def test_accepts_game_data_larger_than_previous_two_megabyte_limit(self):
        body = ndjson(record("game_data", {
            "ActorData": [],
            "ignored_padding": "x" * (2 * 1024 * 1024),
        }))
        self.assertGreater(len(body), 2 * 1024 * 1024)
        response = self.post(body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accepted"], 1)

    @override_settings(INGEST_MAX_BYTES=1024)
    def test_rejects_connector_body_above_configured_limit(self):
        response = self.post(ndjson(record("game_data", {
            "ActorData": [],
            "ignored_padding": "x" * 2048,
        })))
        self.assertEqual(response.status_code, 413)

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

    def test_ingests_allowlisted_numeric_vm_metrics_and_audits_batch(self):
        clock = int(time.time())
        unknown = vm_record("not.allowlisted", 9, clock=clock)
        wrong_type = vm_record("memory.util_pct", "42", value_type=4, clock=clock)

        response = self.post(
            ndjson(
                vm_record("cpu.util_pct", 17.5, clock=clock),
                vm_record("uptime_seconds", 86400, value_type=3, clock=clock),
                unknown,
                wrong_type,
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accepted"], 2)
        self.assertEqual(response.json()["ignored"], 1)
        self.assertEqual(response.json()["rejected"], 1)
        self.assertEqual(VmMetricSample.objects.count(), 2)
        self.assertEqual(
            VmMetricSample.objects.get(metric="cpu.util_pct").value,
            17.5,
        )
        batch = ConnectorBatch.objects.get()
        self.assertEqual(batch.record_count, 4)
        self.assertEqual(batch.datasets, ["vm"])
        self.assertEqual(batch.source_hosts, ["palworld"])
        self.assertEqual(batch.accepted, 2)
        self.assertEqual(batch.ignored, 1)
        self.assertEqual(batch.rejected, 1)
        self.assertEqual(batch.ignored_items, ["Site VM: not.allowlisted"])

    def test_host_tag_does_not_route_untagged_item_values(self):
        value_record = vm_record("cpu.util_pct", 10)
        value_record["item_tags"] = []
        value_record["host_tags"] = [
            {"tag": "integration", "value": "palworld-site"}
        ]

        response = self.post(ndjson(value_record))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accepted"], 0)
        self.assertEqual(response.json()["ignored"], 1)
        self.assertFalse(VmMetricSample.objects.exists())

    def test_null_item_tags_are_ignored_without_failing_the_batch(self):
        value_record = vm_record("docker.containers.running", 2)
        value_record["item_tags"] = None

        response = self.post(ndjson(value_record))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ignored"], 1)
        self.assertFalse(VmMetricSample.objects.exists())

    def test_invalid_utf8_is_included_in_diagnostics(self):
        response = self.post(b"\xff")

        self.assertEqual(response.status_code, 422)
        batch = ConnectorBatch.objects.get()
        self.assertEqual(batch.record_count, 1)
        self.assertEqual(batch.rejected, 1)

    def test_parse_error_details_are_bounded(self):
        invalid_lines = "\n".join("{invalid" for _ in range(20))

        response = self.post(ndjson(record("status", 1)) + "\n" + invalid_lines)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rejected"], 20)
        self.assertEqual(len(response.json()["errors"]), 10)
        self.assertEqual(ConnectorBatch.objects.get().record_count, 21)

    def test_completely_invalid_ndjson_is_included_in_diagnostics(self):
        old_batch = ConnectorBatch.objects.create(record_count=1, rejected=1)
        ConnectorBatch.objects.filter(pk=old_batch.pk).update(
            received_at=timezone.now() - timedelta(days=8)
        )

        response = self.post("{invalid")

        self.assertEqual(response.status_code, 422)
        batch = ConnectorBatch.objects.get()
        self.assertEqual(batch.record_count, 1)
        self.assertEqual(batch.rejected, 1)

    def test_foreign_host_metadata_is_not_retained(self):
        value_record = vm_record("not.allowlisted", 10)
        value_record["host"] = {"host": "foreign-host", "name": "Foreign host"}

        response = self.post(ndjson(value_record))

        self.assertEqual(response.status_code, 200)
        batch = ConnectorBatch.objects.get()
        self.assertEqual(batch.source_hosts, [])
        self.assertEqual(batch.ignored_items, [])

    def test_server_metadata_is_sanitized(self):
        raw_settings = {
            "ServerName": "Public server",
            "CrossplayPlatforms": ["Steam", "Xbox"],
            "PublicIP": "192.0.2.20",
            "PublicPort": 8211,
            "RCONPort": 25575,
            "RESTAPIPort": 8212,
            "AdminPassword": "not-public",
        }
        raw_info = {
            "version": "v1.0.0",
            "servername": "Public server",
            "description": "Public description",
            "worldguid": "PRIVATE-WORLD-GUID",
        }

        response = self.post(
            ndjson(record("settings", raw_settings), record("info", raw_info))
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accepted"], 2)
        settings_payload = LatestDataset.objects.get(key="settings").payload
        self.assertEqual(settings_payload["CrossplayPlatforms"], ["Steam", "Xbox"])
        self.assertEqual(settings_payload["ServerName"], "Public server")
        self.assertNotIn("PublicIP", settings_payload)
        self.assertNotIn("PublicPort", settings_payload)
        self.assertNotIn("RCONPort", settings_payload)
        self.assertNotIn("RESTAPIPort", settings_payload)
        self.assertNotIn("AdminPassword", settings_payload)
        self.assertNotIn("worldguid", LatestDataset.objects.get(key="info").payload)

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

    def test_player_field_aliases_are_normalized_without_leaking_ids(self):
        raw_player = {
            "nickname": "Alias Explorer",
            "account_name": "alias-account",
            "player_uid": "RAW-PLAYER-UID",
            "user_id": "RAW-USER-ID",
            "ip": "192.0.2.30",
            "ping": 42,
            "location_x": None,
            "location_y": None,
            "building_count": None,
            "locationX": -123.5,
            "locationY": 456.25,
            "level": 12,
            "buildingCount": 7,
        }

        response = self.post(ndjson(record("players", {"players": [raw_player]})))

        self.assertEqual(response.status_code, 200)
        player = LatestDataset.objects.get(key="players").payload["players"][0]
        self.assertEqual(player["name"], "Alias Explorer")
        self.assertEqual(player["accountName"], "alias-account")
        self.assertEqual(player["location_x"], -123.5)
        self.assertEqual(player["location_y"], 456.25)
        self.assertEqual(player["building_count"], 7)
        serialized = json.dumps(player)
        self.assertNotIn("RAW-PLAYER-UID", serialized)
        self.assertNotIn("RAW-USER-ID", serialized)
        self.assertNotIn("192.0.2.30", serialized)

    def test_ignores_items_not_selected_for_the_site(self):
        unknown = record("unknown", {"secret": "value"})
        unknown["item_tags"] = [{"tag": "integration", "value": "something-else"}]
        response = self.post(ndjson(unknown))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ignored"], 1)
        self.assertFalse(LatestDataset.objects.exists())


class PortSeparationTests(TestCase):
    def test_ingest_port_allows_private_http_transport(self):
        self.assertFalse(ingest_settings.SECURE_SSL_REDIRECT)

    def test_public_urlconf_does_not_expose_ingest(self):
        response = self.client.post(
            "/api/v1/zabbix/ingest", data="", content_type="application/x-ndjson"
        )
        self.assertEqual(response.status_code, 404)

    @override_settings(
        ROOT_URLCONF="palworld_site.ingest_urls",
        SITE_AUTH_REQUIRED=True,
        ZABBIX_CONNECTOR_TOKEN="test-connector-token",
    )
    def test_site_login_gate_does_not_block_ingest(self):
        response = self.client.post(
            "/api/v1/zabbix/ingest",
            data=ndjson(record("status", 1)),
            content_type="application/x-ndjson",
            HTTP_AUTHORIZATION="Bearer test-connector-token",
        )
        self.assertEqual(response.status_code, 200)

    @override_settings(ROOT_URLCONF="palworld_site.ingest_urls")
    @override_settings(SITE_AUTH_REQUIRED=False)
    def test_ingest_urlconf_does_not_expose_dashboard(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 404)
