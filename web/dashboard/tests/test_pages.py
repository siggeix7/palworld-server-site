from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from dashboard.models import UserProfile


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
            ("vm-dashboard", "Stato della VM"),
        ]
        for name, title in pages:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, title)
                self.assertContains(response, reverse("map"))
                self.assertContains(response, reverse("vm-dashboard"))
                self.assertIn("no-store", response.headers["Cache-Control"])

    def test_home_landing_links_to_each_section(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        for name in ("map", "telemetry", "players", "access", "world", "activity", "vm-dashboard"):
            self.assertContains(response, reverse(name))

    def test_access_page_exposes_credentials_to_approved_members(self):
        response = self.client.get(reverse("access"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "play.example.com")
        self.assertContains(response, "game-server-secret")

    def test_anonymous_visitors_are_redirected_to_login(self):
        self.client.logout()
        for name in ("home", "map", "telemetry", "players", "access", "world", "activity"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])

    def test_vm_page_marks_vm_nav_active(self):
        response = self.client.get(reverse("vm-dashboard"))
        self.assertContains(response, 'aria-current="page"')

    def test_admin_link_only_for_site_admins(self):
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, reverse("members"))

        admin = self.create_user("administrator", "admin@example.com", admin=True)
        self.client.force_login(admin)
        response = self.client.get(reverse("home"))
        self.assertContains(response, reverse("members"))
