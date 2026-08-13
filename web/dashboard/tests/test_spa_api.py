from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.models import UserProfile


@override_settings(
    SITE_AUTH_REQUIRED=True,
    SITE_ADMIN_USERS={"admin@example.com"},
    APP_VERSION="test-build",
    PALWORLD_PUBLIC_HOST="play.example.com",
    PALWORLD_PUBLIC_PORT="8211",
    PALWORLD_PUBLIC_PASSWORD="game-server-secret",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class SpaApiTests(TestCase):
    password = "A-valid-test-password-782!"

    def create_user(self, username, email):
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
        return user

    def setUp(self):
        self.member = self.create_user("member", "member@example.com")
        self.client.force_login(self.member)

    def test_session_returns_member_identity_and_account_routes(self):
        response = self.client.get(reverse("session-api"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "authenticated": True,
            "user": {"username": "member", "email": "member@example.com"},
            "siteAdmin": False,
            "appVersion": "test-build",
            "routes": {
                "terms": reverse("terms"),
                "profile": reverse("change-username"),
                "password": reverse("password_change"),
                "members": None,
                "admin": None,
            },
        })
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])

    def test_session_returns_admin_routes_only_to_configured_admin(self):
        admin = self.create_user("administrator", "admin@example.com")
        self.client.force_login(admin)

        payload = self.client.get(reverse("session-api")).json()

        self.assertTrue(payload["siteAdmin"])
        self.assertEqual(payload["routes"]["members"], reverse("members"))
        self.assertEqual(payload["routes"]["admin"], reverse("admin-panel"))

    def test_server_access_returns_configured_address_without_caching(self):
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

    @override_settings(PALWORLD_PUBLIC_HOST="")
    def test_server_access_marks_missing_host_as_unconfigured(self):
        payload = self.client.get(reverse("server-access-api")).json()
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["address"], "")

    @override_settings(PALWORLD_PUBLIC_PASSWORD="")
    def test_server_access_marks_missing_password_as_unconfigured(self):
        payload = self.client.get(reverse("server-access-api")).json()
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["address"], "play.example.com:8211")

    def test_bootstrap_endpoints_are_get_only(self):
        self.assertEqual(self.client.post(reverse("session-api")).status_code, 405)
        self.assertEqual(self.client.post(reverse("server-access-api")).status_code, 405)

    def test_anonymous_user_is_rejected_by_existing_middleware(self):
        self.client.logout()
        for name in ("session-api", "server-access-api", "openapi-schema"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"error": "authentication required"})

    def test_openapi_document_covers_public_and_private_endpoints(self):
        response = self.client.get(reverse("openapi-schema"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        document = response.json()
        self.assertEqual(document["openapi"], "3.1.0")

        public_paths = {
            "/api/v1/session",
            "/api/v1/server/access",
            "/api/v1/snapshot",
            "/api/v1/history",
            "/api/v1/players",
            "/api/v1/player/{public_id}",
            "/api/v1/leaderboard",
            "/api/v1/activity/heatmap",
            "/api/v1/world/objects",
            "/api/v1/live-map/config",
            "/api/v1/live-map/catalogue",
            "/api/v1/live-map/players",
            "/api/v1/live-map/objects",
            "/api/v1/telemetry/stats",
            "/api/v1/world/diff",
            "/api/v1/palworld/players",
            "/api/v1/admin/player-ips",
            "/api/v1/admin/weekly-report-schedule",
            "/api/v1/palworld/info",
            "/api/v1/palworld/admin/players",
            "/api/v1/palworld/announce",
            "/api/v1/palworld/kick",
            "/api/v1/palworld/ban",
            "/api/v1/palworld/unban",
            "/api/v1/guild/data",
        }
        private_paths = {
            "/healthz/",
            "/api/v1/collector/status",
            "/api/v1/guild/ingest",
        }
        self.assertTrue(public_paths <= set(document["paths"]))
        self.assertTrue(private_paths <= set(document["paths"]))

        operation_ids = [
            operation["operationId"]
            for path_item in document["paths"].values()
            for method, operation in path_item.items()
            if method in {"get", "post", "put", "patch", "delete"}
        ]
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        self.assertIn("Error", document["components"]["schemas"])
        self.assertIn("cookieAuth", document["components"]["securitySchemes"])
        self.assertIn("bearerAuth", document["components"]["securitySchemes"])
        self.assertIn(
            "requestBody",
            document["paths"]["/api/v1/palworld/announce"]["post"],
        )
        self.assertIn(
            "requestBody",
            document["paths"]["/api/v1/guild/ingest"]["post"],
        )
