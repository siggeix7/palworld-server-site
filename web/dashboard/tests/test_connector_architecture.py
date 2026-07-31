from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class ConnectorArchitectureTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = Path(settings.BASE_DIR).parent

    def read(self, relative_path):
        return (self.root / relative_path).read_text(encoding="utf-8")

    def test_web_container_has_no_palworld_rest_credentials_or_watcher(self):
        compose = self.read("docker-compose.yml")
        entrypoint = self.read("docker/entrypoint.sh")
        django_settings = self.read("web/palworld_site/settings.py")
        combined = "\n".join((compose, entrypoint, django_settings))
        self.assertNotIn("PALWORLD_API_URL", combined)
        self.assertNotIn("PALWORLD_API_PASSWORD", combined)
        self.assertNotIn("watch_players", combined)

    def test_admin_routes_do_not_proxy_palworld_commands(self):
        urls = self.read("web/palworld_site/urls.py")
        admin_views = self.read("web/dashboard/admin_views.py")
        for path in ("palworld/announce", "palworld/kick", "palworld/ban", "palworld/unban"):
            self.assertNotIn(path, urls)
        self.assertNotIn("PalworldAPIClient", admin_views)
        self.assertNotIn("requests.", admin_views)

    def test_zabbix_collects_game_data_at_live_cadence(self):
        template = self.read("zabbix/palworld-server-site.yaml")
        raw_item = template.split("key: palworld.game_data\n", 1)[1].split("- uuid:", 1)[0]
        self.assertIn("delay: '{$PALGAMEDATAINTERVAL}'", raw_item)
        self.assertIn("macro: '{$PALGAMEDATAINTERVAL}'", template)
        self.assertIn("value: 15s", template)
        self.assertIn("history: '0'", raw_item)
        self.assertIn("/v1/api/game-data", raw_item)
        self.assertNotIn("integration", raw_item)
        self.assertEqual(template.count("value: game_data_chunk"), 12)
        self.assertEqual(template.count("value_type: BINARY"), 12)
        self.assertEqual(template.count("palworld.game_data.chunk["), 12)
        self.assertNotIn("palworld.game_data.compact", template)
        self.assertIn(
            "net.tcp.service[{$PALAPISCHEME},{$PALAPIIP},{$PALAPIPORT}]",
            template,
        )
        self.assertEqual(template.count("verify_peer: 'YES'"), 5)
        self.assertEqual(template.count("verify_host: 'YES'"), 5)

    def test_connector_exports_binary_values_in_bounded_batches(self):
        connector = self.read("zabbix/connector.md")
        self.assertIn("Text, Binary", connector)
        self.assertNotIn("Type of information:      All", connector)
        self.assertIn("Max records per message:  3", connector)

    def test_receiver_and_map_expose_world_data_diagnostics(self):
        self.assertGreaterEqual(settings.INGEST_MAX_BYTES, 64 * 1024 * 1024)
        ingest_settings = self.read("web/palworld_site/ingest_settings.py")
        self.assertIn("DATA_UPLOAD_MAX_MEMORY_SIZE = INGEST_MAX_BYTES", ingest_settings)
        template = self.read("web/dashboard/templates/dashboard/map.html")
        script = self.read("web/dashboard/static/dashboard/js/site.js")
        self.assertIn('id="worldObjectStatus"', template)
        self.assertIn("Game-data via Zabbix", script)
        for kind in ("wild-pals", "npcs", "companions", "workers"):
            self.assertIn(kind, script)
        self.assertIn("combinedBases", script)
