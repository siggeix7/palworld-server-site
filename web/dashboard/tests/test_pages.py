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

    def test_each_section_page_renders_with_nav_and_title(self):
        pages = [
            ("map", "Mappa"),
            ("telemetry", "Telemetria"),
            ("players", "Giocatori"),
            ("access", "Accesso"),
            ("world", "Mondo"),
            ("activity", "Attività"),
            ("terms", "Condizioni d'uso e informativa privacy"),
        ]
        for name, title in pages:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, title)
                self.assertContains(response, reverse("map"))
                self.assertIn("no-store", response.headers["Cache-Control"])

    def test_players_page_explains_save_history_source(self):
        response = self.client.get(reverse("players"))
        self.assertContains(response, "Level.sav")
        self.assertContains(response, "non è necessario essere registrati al sito")

    def test_home_landing_links_to_each_section(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        for name in ("map", "telemetry", "players", "access", "world", "activity"):
            self.assertContains(response, reverse(name))

    def test_access_page_exposes_credentials_to_approved_members(self):
        response = self.client.get(reverse("access"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "play.example.com")
        self.assertContains(response, "game-server-secret")

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

    def test_page_specific_scripts_keep_shared_site_script(self):
        for name, script in (
            ("guilds", "dashboard/js/guilds.js"),
            ("admin-panel", "dashboard/js/admin.js"),
        ):
            if name == "admin-panel":
                admin = self.create_user(
                    "script-admin", "admin@example.com", admin=True
                )
                self.client.force_login(admin)
            response = self.client.get(reverse(name))
            self.assertContains(response, "dashboard/js/site.js", count=1)
            self.assertContains(response, script, count=1)

    def test_anonymous_visitors_are_redirected_to_login(self):
        self.client.logout()
        for name in ("home", "map", "telemetry", "players", "access", "world", "activity"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])

    def test_admin_link_only_for_site_admins(self):
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, reverse("members"))

        admin = self.create_user("administrator", "admin@example.com", admin=True)
        self.client.force_login(admin)
        response = self.client.get(reverse("home"))
        self.assertContains(response, reverse("members"))
