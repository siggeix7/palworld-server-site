from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.models import GuildSnapshot, UserProfile


@override_settings(
    SITE_AUTH_REQUIRED=True,
    SITE_ADMIN_USERS={"admin@example.com"},
    CSRF_TRUSTED_ORIGINS=["https://palworld.example.com"],
    PUBLIC_SITE_URL="https://palworld.example.com",
    PALWORLD_PUBLIC_HOST="play.example.com",
    PALWORLD_PUBLIC_PORT="8211",
    PALWORLD_PUBLIC_PASSWORD="game-server-secret",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class SectionPageTests(TestCase):
    password = "A-valid-test-password-782!"

    def create_user(self, username="member", email="member@example.com", admin=False):
        user = get_user_model().objects.create_user(
            username=username,
            email=email,
            password=self.password,
        )
        UserProfile.objects.create(
            user=user,
            email_verified=True,
            approved=True,
            terms_version=settings.CURRENT_TERMS_VERSION,
            terms_accepted_at=timezone.now(),
        )
        if admin:
            self.assertEqual(email, "admin@example.com")
        return user

    def setUp(self):
        self.member = self.create_user()
        self.client.force_login(self.member)

    def assert_spa_shell(self, response, status_code=200):
        self.assertEqual(response.status_code, status_code)
        self.assertTemplateUsed(response, "dashboard/app.html")
        self.assertContains(response, 'id="root"', status_code=status_code)
        self.assertContains(
            response,
            "dashboard/live-map/live-map.css",
            status_code=status_code,
        )
        self.assertContains(
            response,
            "dashboard/live-map/live-map.js",
            status_code=status_code,
        )
        self.assertNotContains(
            response,
            "dashboard/js/site.js",
            status_code=status_code,
        )
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])

    def test_each_dashboard_section_uses_the_same_spa_shell(self):
        pages = [
            "home",
            "map",
            "telemetry",
            "players",
            "access",
            "world",
            "activity",
            "leaderboard",
            "peak-hours",
            "guilds",
        ]
        for name in pages:
            with self.subTest(page=name):
                self.assert_spa_shell(self.client.get(reverse(name)))

    def test_terms_page_remains_server_rendered(self):
        response = self.client.get(reverse("terms"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/terms.html")
        self.assertContains(response, "Condizioni d'uso e informativa privacy")
        self.assertNotContains(response, "dashboard/live-map/live-map.js")

    def test_players_page_no_longer_renders_legacy_content(self):
        response = self.client.get(reverse("players"))
        self.assert_spa_shell(response)
        self.assertNotContains(response, "Level.sav")
        self.assertNotContains(response, "dashboard/js/player.js")

    def test_home_shell_contains_only_minimal_bootstrap_metadata(self):
        response = self.client.get(reverse("home"))
        self.assert_spa_shell(response)
        self.assertContains(response, 'name="application-version"')
        self.assertNotContains(response, "member@example.com")
        self.assertNotContains(response, "game-server-secret")

    def test_access_credentials_are_exposed_only_by_the_private_response_api(self):
        page_response = self.client.get(reverse("access"))
        self.assert_spa_shell(page_response)
        self.assertNotContains(page_response, "play.example.com")
        self.assertNotContains(page_response, "game-server-secret")

        response = self.client.get(reverse("server-access-api"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "host": "play.example.com",
            "port": "8211",
            "password": "game-server-secret",
            "address": "play.example.com:8211",
            "configured": True,
        })
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])

    def test_guild_data_exposes_bases_to_approved_members(self):
        GuildSnapshot.objects.create(
            payload={
                "schema_version": 2,
                "guilds": [{
                    "group_id": "guild-1",
                    "guild_name": "Explorers",
                    "players": [{"player_name": "Member"}],
                }],
                "bases": [{
                    "base_id": "base-1",
                    "group_id": "guild-1",
                    "name": "Forte Nord",
                    "problem_worker_count": 2,
                }],
                "world": {"active_raid_count": 0, "oil_rig_count": 3},
            }
        )
        response = self.client.get(reverse("guild-data"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["bases"][0]["base_id"], "base-1")
        self.assertEqual(response.json()["world"]["oil_rig_count"], 3)
        self.assertFalse(response.json()["stale"])
        self.assertNotIn("alerts", response.json())

    def test_guild_data_exposes_compact_alerts_only_to_admins(self):
        snapshot = GuildSnapshot.objects.create(
            payload={
                "schema_version": 2,
                "guilds": [{
                    "group_id": "guild-1",
                    "guild_name": "Explorers",
                    "players": [],
                }],
                "bases": [{
                    "base_id": "base-1",
                    "group_id": "guild-1",
                    "name": "Forte Nord",
                    "problem_worker_count": 2,
                    "raid_active": True,
                }],
                "diagnostics": {"unresolved_worker_count": 1},
                "world": {"active_raid_count": 2, "oil_rig_alert_count": 1},
            }
        )
        GuildSnapshot.objects.filter(pk=snapshot.pk).update(
            updated_at=timezone.now() - timedelta(minutes=20)
        )
        member_payload = self.client.get(reverse("guild-data")).json()
        self.assertNotIn("alerts", member_payload)
        self.assertTrue(member_payload["stale"])

        admin = self.create_user("administrator", "admin@example.com", admin=True)
        self.client.force_login(admin)
        payload = self.client.get(reverse("guild-data")).json()
        titles = {alert["title"] for alert in payload["alerts"]}
        self.assertIn("Sincronizzazione save in ritardo", titles)
        self.assertIn("Gilda senza membri", titles)
        self.assertIn("Pal in difficoltà", titles)
        self.assertIn("Invasione attiva", titles)
        self.assertIn("Riferimenti save scollegati", titles)
        self.assertIn("Allarme piattaforma petrolifera", titles)
        self.assertIn("Invasione non associata", titles)

    def test_legacy_page_scripts_are_replaced_by_the_single_spa_bundle(self):
        for name, legacy_script in (
            ("guilds", "dashboard/js/guilds.js"),
            ("admin-panel", "dashboard/js/admin.js"),
        ):
            if name == "admin-panel":
                admin = self.create_user(
                    "script-admin", "admin@example.com", admin=True
                )
                self.client.force_login(admin)
            response = self.client.get(reverse(name))
            self.assert_spa_shell(response)
            self.assertContains(response, "dashboard/live-map/live-map.js", count=1)
            self.assertNotContains(response, legacy_script)

    def test_anonymous_visitors_are_redirected_to_login(self):
        self.client.logout()
        for name in (
            "home",
            "map",
            "telemetry",
            "players",
            "access",
            "world",
            "activity",
            "leaderboard",
            "peak-hours",
            "guilds",
            "admin-panel",
        ):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])

        for name in (
            "live-map-config",
            "live-map-catalogue",
            "live-map-players",
            "live-map-objects",
            "session-api",
            "server-access-api",
            "openapi-schema",
        ):
            with self.subTest(api=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 401)

    def test_admin_routes_are_only_bootstrapped_for_site_admins(self):
        payload = self.client.get(reverse("session-api")).json()
        self.assertIsNone(payload["routes"]["members"])
        self.assertIsNone(payload["routes"]["admin"])

        admin = self.create_user("administrator", "admin@example.com", admin=True)
        self.client.force_login(admin)
        payload = self.client.get(reverse("session-api")).json()
        self.assertEqual(payload["routes"]["members"], reverse("members"))
        self.assertEqual(payload["routes"]["admin"], reverse("admin-panel"))
