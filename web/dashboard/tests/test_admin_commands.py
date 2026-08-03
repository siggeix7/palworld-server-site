from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.admin_views import PalworldCommandClient, PalworldCommandError
from dashboard.models import Player, UserProfile


@override_settings(
    SITE_ADMIN_USERS={"admin"},
    PALWORLD_API_URL="http://palworld.example.com:8212",
    PALWORLD_API_USER="admin",
    PALWORLD_API_PASSWORD="secret",
    PALWORLD_API_VERIFY_TLS=False,
    PALWORLD_API_ALLOW_INSECURE_HTTP=True,
    CSRF_TRUSTED_ORIGINS=["https://palworld.example.com"],
    PUBLIC_SITE_URL="https://palworld.example.com",
)
class AdminCommandTests(TestCase):
    password = "A-valid-test-password-782!"

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin", email="admin@example.com", password=self.password
        )
        UserProfile.objects.create(
            user=self.admin,
            email_verified=True,
            approved=True,
            terms_version=settings.CURRENT_TERMS_VERSION,
            terms_accepted_at=timezone.now(),
        )
        self.member = User.objects.create_user(
            username="member", email="member@example.com", password=self.password
        )
        UserProfile.objects.create(
            user=self.member,
            email_verified=True,
            approved=True,
            terms_version=settings.CURRENT_TERMS_VERSION,
            terms_accepted_at=timezone.now(),
        )

    def test_non_member_gets_403_on_every_command(self):
        self.client.force_login(self.member)
        cases = [
            ("post", reverse("palworld-announce"), {"message": "hi"}),
            ("post", reverse("palworld-kick"), {"userid": "123"}),
            ("post", reverse("palworld-ban"), {"userid": "123"}),
            ("post", reverse("palworld-unban"), {"userid": "123"}),
        ]
        for method, url, body in cases:
            with self.subTest(url=url):
                response = getattr(self.client, method)(
                    url, data=body, content_type="application/json"
                )
                self.assertEqual(response.status_code, 403)
        response = self.client.get(reverse("palworld-admin-players"))
        self.assertEqual(response.status_code, 403)

    def test_admin_panel_exposes_command_controls_only_to_admin(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("admin-panel")).status_code, 403)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin-panel"))
        self.assertEqual(response.status_code, 200)
        for element_id in (
            "announceForm",
            "commandPlayersTable",
            "refreshCommandPlayers",
            "unbanForm",
            "playerIpsTable",
        ):
            self.assertContains(response, f'id="{element_id}"')
        self.assertIn("csrftoken", response.cookies)

    def test_stored_player_ips_are_admin_only(self):
        now = timezone.now()
        Player.objects.create(
            public_id="a" * 24,
            name="Explorer",
            account_name="Account",
            first_seen=now - timedelta(days=2),
            last_seen=now - timedelta(minutes=2),
            ip_address="2001:db8::44",
            ip_observed_at=now - timedelta(minutes=2),
        )

        self.client.force_login(self.member)
        response = self.client.get(reverse("admin-player-ips"))
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin-player-ips"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["players"][0]["name"], "Explorer")
        self.assertEqual(payload["players"][0]["ip"], "2001:db8::44")

    def test_admin_commands_require_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        payload = {"message": "Maintenance soon"}
        response = csrf_client.post(
            reverse("palworld-announce"), payload, content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)

        page = csrf_client.get(reverse("admin-panel"))
        token = page.cookies["csrftoken"].value
        with mock.patch("dashboard.admin_views.PalworldCommandClient"):
            response = csrf_client.post(
                reverse("palworld-announce"),
                payload,
                content_type="application/json",
                HTTP_X_CSRFTOKEN=token,
            )
        self.assertEqual(response.status_code, 200)

    def test_admin_announce_validates_message_and_calls_palworld(self):
        self.client.force_login(self.admin)
        with mock.patch("dashboard.admin_views.PalworldCommandClient") as client_cls:
            client_cls.return_value.announce.return_value = {}
            response = self.client.post(
                reverse("palworld-announce"),
                data={"message": "Server restarting in 5 minutes"},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            client_cls.return_value.announce.assert_called_once_with(
                "Server restarting in 5 minutes"
            )

        for body in (
            {"message": "   "},
            {"message": ""},
            {"message": "x" * 501},
            {"message": "bad\nmessage"},
            [],
        ):
            with self.subTest(body=body):
                response = self.client.post(
                    reverse("palworld-announce"),
                    data=body,
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
        response = self.client.post(
            reverse("palworld-announce"), data="{}", content_type="text/plain"
        )
        self.assertEqual(response.status_code, 415)

    def test_admin_kick_ban_unban_validate_userid_and_call_palworld(self):
        self.client.force_login(self.admin)
        for route_name, method_name in (
            ("palworld-kick", "kick"),
            ("palworld-ban", "ban"),
            ("palworld-unban", "unban"),
        ):
            with mock.patch("dashboard.admin_views.PalworldCommandClient") as client_cls:
                response = self.client.post(
                    reverse(route_name),
                    data={"userid": "76561198000000000"},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200)
                getattr(client_cls.return_value, method_name).assert_called_once_with(
                    "76561198000000000"
                )

        for userid in ("", "   ", "with spaces", "x" * 65, 123):
            with self.subTest(userid=userid):
                response = self.client.post(
                    reverse("palworld-kick"),
                    data={"userid": userid},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
        response = self.client.post(
            reverse("palworld-kick"), data="{}", content_type="text/plain"
        )
        self.assertEqual(response.status_code, 415)

    def test_palworld_failure_is_reported_as_502(self):
        self.client.force_login(self.admin)
        with mock.patch("dashboard.admin_views.PalworldCommandClient") as client_cls:
            client_cls.return_value.kick.side_effect = PalworldCommandError(
                "Palworld authentication failed"
            )
            response = self.client.post(
                reverse("palworld-kick"),
                data={"userid": "76561198000000000"},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 502)
            self.assertIn("authentication failed", response.json()["error"])

    def test_admin_players_returns_minimal_sanitized_list(self):
        self.client.force_login(self.admin)
        raw_players = [
            {
                "userId": "76561198000000000",
                "name": "Explorer",
                "level": 50,
                "ping": 22.5,
                "location_x": -100,
                "location_y": 200,
                "ip": "192.0.2.10",
                "playerId": "raw-player-uuid",
            },
            {"userId": "  ", "name": "Bad"},
            {"name": "NoUserId"},
            {"userId": "with spaces", "name": "Invalid"},
            {"playerId": "fallback-player-id", "name": "Fallback"},
        ]
        with mock.patch("dashboard.admin_views.PalworldCommandClient") as client_cls:
            client_cls.return_value.players.return_value = raw_players
            response = self.client.get(reverse("palworld-admin-players"))
        self.assertEqual(response.status_code, 200)
        players = response.json()["players"]
        self.assertEqual(len(players), 2)
        player = players[0]
        self.assertEqual(player["userId"], "76561198000000000")
        self.assertEqual(player["name"], "Explorer")
        self.assertEqual(player["level"], 50)
        self.assertEqual(player["ping"], 22.5)
        self.assertNotIn("ip", player)
        self.assertNotIn("playerId", player)
        fallback = next(item for item in players if item["name"] == "Fallback")
        self.assertEqual(fallback["userId"], "fallback-player-id")
        serialized = response.content.decode()
        self.assertNotIn("raw-player-uuid", serialized)
        self.assertNotIn("192.0.2.10", serialized)

    def test_admin_players_reports_palworld_failure_as_502(self):
        self.client.force_login(self.admin)
        with mock.patch("dashboard.admin_views.PalworldCommandClient") as client_cls:
            client_cls.return_value.players.side_effect = PalworldCommandError(
                "Palworld unreachable"
            )
            response = self.client.get(reverse("palworld-admin-players"))
            self.assertEqual(response.status_code, 502)

    def test_command_client_uses_expected_palworld_endpoints_and_payloads(self):
        response = mock.Mock(
            status_code=200,
            ok=True,
            content=b"{}",
            text="{}",
        )
        response.json.return_value = {}
        session = mock.Mock()
        session.request.return_value = response
        with mock.patch("dashboard.admin_views.requests.Session", return_value=session):
            client = PalworldCommandClient()
            client.announce("Hello")
            client.kick("u1")
            client.ban("u2")
            client.unban("u3")

        expected = [
            ("POST", "http://palworld.example.com:8212/v1/api/announce", {"message": "Hello"}),
            ("POST", "http://palworld.example.com:8212/v1/api/kick", {"userid": "u1"}),
            ("POST", "http://palworld.example.com:8212/v1/api/ban", {"userid": "u2"}),
            ("POST", "http://palworld.example.com:8212/v1/api/unban", {"userid": "u3"}),
        ]
        self.assertEqual(len(session.request.call_args_list), len(expected))
        for call, (method, url, body) in zip(session.request.call_args_list, expected):
            self.assertEqual(call.args, (method, url))
            self.assertEqual(call.kwargs["json"], body)
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertFalse(call.kwargs["verify"])
