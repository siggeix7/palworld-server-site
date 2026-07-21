from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from dashboard.accounts import get_user_profile
from dashboard.models import AuthThrottle, UserProfile
from dashboard.tokens import email_verification_token


@override_settings(
    SITE_AUTH_REQUIRED=True,
    SITE_ADMIN_USERS={"admin@example.com"},
    CSRF_TRUSTED_ORIGINS=["https://palworld.example.com"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="site@example.com",
    PUBLIC_SITE_URL="https://palworld.example.com",
    PALWORLD_PUBLIC_HOST="play.example.com",
    PALWORLD_PUBLIC_PORT="8211",
    PALWORLD_PUBLIC_PASSWORD="game-server-secret",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class AccountAccessTests(TestCase):
    password = "A-valid-test-password-782!"

    def create_user(
        self,
        username="member",
        email="member@example.com",
        *,
        verified=False,
        approved=False,
        must_change_password=False,
    ):
        user = get_user_model().objects.create_user(
            username=username,
            email=email,
            password=self.password,
        )
        UserProfile.objects.create(
            user=user,
            email_verified=verified,
            approved=approved,
            must_change_password=must_change_password,
        )
        return user

    def create_admin(self):
        admin = self.create_user(
            username="administrator",
            email="admin@example.com",
            verified=True,
        )
        get_user_profile(admin)
        return admin

    def test_anonymous_visitors_are_redirected_and_apis_return_401(self):
        response = self.client.get("/")
        self.assertRedirects(
            response,
            f"{reverse('login')}?next=%2F",
            fetch_redirect_response=False,
        )
        response = self.client.get(reverse("snapshot"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "authentication required"})
        self.assertNotContains(response, "game-server-secret", status_code=401)

    def test_health_and_account_entry_points_remain_public(self):
        self.assertEqual(self.client.get(reverse("health")).status_code, 200)
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        self.assertEqual(self.client.get(reverse("register")).status_code, 200)

    def test_unapproved_account_cannot_open_dashboard_or_api(self):
        user = self.create_user(verified=True)
        self.client.force_login(user)

        self.assertRedirects(
            self.client.get(reverse("home")),
            reverse("pending-approval"),
            fetch_redirect_response=False,
        )
        response = self.client.get(reverse("snapshot"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "account approval required"})

    def test_approved_account_sees_credentials_in_non_cacheable_page(self):
        user = self.create_user(verified=True, approved=True)
        self.client.force_login(user)

        response = self.client.get(reverse("access"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "play.example.com")
        self.assertContains(response, "game-server-secret")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])

    def test_registration_creates_pending_profile_and_sends_verification(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "NewMember",
                "email": "NewMember@Example.com",
                "password1": self.password,
                "password2": self.password,
            },
        )

        self.assertRedirects(response, reverse("registration-done"))
        user = get_user_model().objects.get(username="NewMember")
        self.assertEqual(user.email, "newmember@example.com")
        self.assertFalse(user.site_profile.email_verified)
        self.assertFalse(user.site_profile.approved)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("https://palworld.example.com/accounts/verify/", mail.outbox[0].body)

    @override_settings(ALLOWED_HOSTS=["internal.example"])
    def test_registration_accepts_canonical_origin_behind_proxy(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.get(
            reverse("register"),
            secure=True,
            HTTP_HOST="internal.example",
        )
        token = response.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("register"),
            {
                "csrfmiddlewaretoken": token,
                "username": "ProxyMember",
                "email": "proxy@example.com",
                "password1": self.password,
                "password2": self.password,
            },
            secure=True,
            HTTP_HOST="internal.example",
            HTTP_ORIGIN="https://palworld.example.com",
        )

        self.assertRedirects(response, reverse("registration-done"))
        self.assertTrue(get_user_model().objects.filter(username="ProxyMember").exists())

    def test_registration_rejects_case_insensitive_identifier_collisions(self):
        self.create_user(username="ExistingName", email="existing@example.com")
        response = self.client.post(
            reverse("register"),
            {
                "username": "existingname",
                "email": "other@example.com",
                "password1": self.password,
                "password2": self.password,
            },
        )
        self.assertContains(response, "Esiste già un account con questo username.")
        self.assertEqual(get_user_model().objects.count(), 1)

        response = self.client.post(
            reverse("register"),
            {
                "username": "OtherMember",
                "email": "EXISTING@example.com",
                "password1": self.password,
                "password2": self.password,
            },
        )
        self.assertContains(response, "Esiste già un account con questa email.")
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_registration_cannot_claim_configured_admin_email_as_username(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "admin@example.com",
                "email": "attacker@example.net",
                "password1": self.password,
                "password2": self.password,
            },
        )

        self.assertContains(response, "Lo username non può contenere il carattere @.")
        self.assertFalse(get_user_model().objects.exists())

        legacy_user = self.create_user(
            username="admin@example.com",
            email="attacker@example.net",
            verified=True,
        )
        self.client.force_login(legacy_user)
        self.assertEqual(self.client.get(reverse("members")).status_code, 403)

    @override_settings(SITE_ADMIN_USERS={"administrator"})
    def test_registration_cannot_claim_configured_admin_username(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "Administrator",
                "email": "attacker@example.net",
                "password1": self.password,
                "password2": self.password,
            },
        )

        self.assertContains(response, "Questo username è riservato.")
        self.assertFalse(get_user_model().objects.exists())

    def test_database_enforces_case_insensitive_identity_uniqueness(self):
        self.create_user(username="CaseMember", email="case@example.com")
        with self.assertRaises(IntegrityError), transaction.atomic():
            get_user_model().objects.create_user(
                username="casemember",
                email="other@example.com",
                password=self.password,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            get_user_model().objects.create_user(
                username="OtherMember",
                email="CASE@example.com",
                password=self.password,
            )

    def test_verification_marks_email_and_notifies_admin(self):
        user = self.create_user()
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_verification_token.make_token(user)

        verification_url = reverse(
            "verify-email", kwargs={"uidb64": uid, "token": token}
        )
        response = self.client.get(verification_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])
        user.site_profile.refresh_from_db()
        self.assertFalse(user.site_profile.email_verified)
        self.assertEqual(len(mail.outbox), 0)

        response = self.client.post(verification_url)

        self.assertRedirects(response, reverse("pending-approval"))
        user.site_profile.refresh_from_db()
        self.assertTrue(user.site_profile.email_verified)
        self.assertFalse(user.site_profile.approved)
        self.assertIsNotNone(user.site_profile.admin_notified_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["admin@example.com"])

        self.client.get(reverse("pending-approval"))
        self.assertEqual(len(mail.outbox), 1)

        response = self.client.get(verification_url)
        self.assertEqual(response.status_code, 400)

    def test_configured_admin_still_has_to_verify_email(self):
        admin = self.create_user(
            username="administrator",
            email="ADMIN@example.com",
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("home"))

        self.assertRedirects(
            response,
            reverse("pending-approval"),
            fetch_redirect_response=False,
        )
        admin.site_profile.refresh_from_db()
        self.assertTrue(admin.site_profile.approved)
        self.assertFalse(admin.site_profile.email_verified)
        self.assertEqual(self.client.get(reverse("members")).status_code, 403)

        admin.site_profile.email_verified = True
        admin.site_profile.save(update_fields=["email_verified"])
        self.assertEqual(self.client.get(reverse("members")).status_code, 200)

    def test_admin_can_approve_and_revoke_verified_member(self):
        admin = self.create_admin()
        member = self.create_user(verified=True)
        self.client.force_login(admin)

        response = self.client.post(
            reverse("members"),
            {"profile_id": member.site_profile.pk, "action": "approve"},
        )

        self.assertRedirects(response, reverse("members"))
        member.site_profile.refresh_from_db()
        self.assertTrue(member.site_profile.approved)
        self.assertEqual(member.site_profile.approved_by, admin)
        self.assertEqual(len(mail.outbox), 1)

        response = self.client.post(
            reverse("members"),
            {"profile_id": member.site_profile.pk, "action": "revoke"},
        )
        self.assertRedirects(response, reverse("members"))
        member.site_profile.refresh_from_db()
        self.assertFalse(member.site_profile.approved)
        self.assertIsNone(member.site_profile.approved_by)

    def test_admin_can_delete_a_member_after_confirmation(self):
        admin = self.create_admin()
        member = self.create_user(username="delete-me", email="delete@example.com")
        self.client.force_login(admin)
        delete_url = reverse("member-delete", kwargs={"profile_id": member.site_profile.pk})

        response = self.client.get(delete_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "delete-me")
        self.assertTrue(get_user_model().objects.filter(pk=member.pk).exists())

        response = self.client.post(delete_url)
        self.assertRedirects(response, reverse("members"))
        self.assertFalse(get_user_model().objects.filter(pk=member.pk).exists())

    def test_configured_admin_cannot_be_deleted(self):
        admin = self.create_admin()
        self.client.force_login(admin)
        delete_url = reverse("member-delete", kwargs={"profile_id": admin.site_profile.pk})

        self.assertEqual(self.client.get(delete_url).status_code, 403)
        self.assertEqual(self.client.post(delete_url).status_code, 403)
        self.assertTrue(get_user_model().objects.filter(pk=admin.pk).exists())

    @override_settings(SITE_ADMIN_USERS={"administrator"})
    def test_pending_notification_resolves_username_admin_email(self):
        self.create_user(
            username="Administrator",
            email="admin-by-username@example.com",
            verified=True,
            approved=True,
        )
        member = self.create_user(username="pending-member", email="pending@example.com")
        uid = urlsafe_base64_encode(force_bytes(member.pk))
        token = email_verification_token.make_token(member)

        self.client.post(
            reverse("verify-email", kwargs={"uidb64": uid, "token": token})
        )

        member.site_profile.refresh_from_db()
        self.assertIsNotNone(member.site_profile.admin_notified_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["admin-by-username@example.com"])

    def test_pending_page_retries_failed_admin_notification(self):
        member = self.create_user(verified=True)
        self.client.force_login(member)

        with mock.patch(
            "dashboard.account_views.notify_admins_of_pending_user",
            side_effect=RuntimeError("smtp unavailable"),
        ):
            response = self.client.get(reverse("pending-approval"))
        self.assertEqual(response.status_code, 200)
        member.site_profile.refresh_from_db()
        self.assertIsNone(member.site_profile.admin_notified_at)

        with mock.patch(
            "dashboard.account_views.notify_admins_of_pending_user",
            return_value=1,
        ):
            response = self.client.get(reverse("pending-approval"))
        self.assertEqual(response.status_code, 200)
        member.site_profile.refresh_from_db()
        self.assertIsNotNone(member.site_profile.admin_notified_at)

    def test_admin_cannot_approve_an_unverified_member(self):
        admin = self.create_admin()
        member = self.create_user()
        self.client.force_login(admin)

        self.client.post(
            reverse("members"),
            {"profile_id": member.site_profile.pk, "action": "approve"},
        )

        member.site_profile.refresh_from_db()
        self.assertFalse(member.site_profile.approved)
        self.assertEqual(len(mail.outbox), 0)

    def test_non_admin_cannot_open_member_management(self):
        member = self.create_user(verified=True, approved=True)
        target = self.create_user(
            username="target",
            email="target@example.com",
            verified=True,
            approved=True,
        )
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse("members")).status_code, 403)
        self.assertEqual(
            self.client.get(
                reverse("member-delete", kwargs={"profile_id": target.site_profile.pk})
            ).status_code,
            403,
        )

    def test_login_accepts_email_case_insensitively(self):
        self.create_user(verified=True, approved=True)

        response = self.client.post(
            reverse("login"),
            {"username": "MEMBER@EXAMPLE.COM", "password": self.password},
        )

        self.assertRedirects(response, reverse("home"))

    def test_temporary_password_must_be_changed_before_site_access(self):
        user = self.create_user(
            verified=True,
            approved=True,
            must_change_password=True,
        )
        self.client.force_login(user)

        self.assertRedirects(
            self.client.get(reverse("home")),
            reverse("password_change"),
            fetch_redirect_response=False,
        )
        response = self.client.get(reverse("snapshot"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "password change required"})

        new_password = "A-new-valid-test-password-963!"
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": self.password,
                "new_password1": new_password,
                "new_password2": new_password,
            },
        )

        self.assertRedirects(response, reverse("home"))
        user.site_profile.refresh_from_db()
        user.refresh_from_db()
        self.assertFalse(user.site_profile.must_change_password)
        self.assertTrue(user.check_password(new_password))
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_login_rate_limit_is_shared_through_the_database(self):
        for _attempt in range(10):
            response = self.client.post(
                reverse("login"),
                {"username": "unknown", "password": "invalid-password"},
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("login"),
            {"username": "unknown", "password": "invalid-password"},
        )

        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers["Retry-After"]), 0)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_csrf_rejections_do_not_consume_login_quota(self):
        csrf_client = Client(enforce_csrf_checks=True)

        for _attempt in range(11):
            response = csrf_client.post(
                reverse("login"),
                {"username": "unknown", "password": "invalid-password"},
            )
            self.assertEqual(response.status_code, 403)

        self.assertFalse(AuthThrottle.objects.exists())

    @override_settings(
        ALLOWED_HOSTS=["hostile.example"],
        USE_X_FORWARDED_HOST=True,
    )
    def test_password_reset_uses_canonical_host(self):
        self.create_user(verified=True, approved=True)

        response = self.client.post(
            reverse("password_reset"),
            {"email": "member@example.com"},
            HTTP_HOST="hostile.example",
            HTTP_X_FORWARDED_HOST="hostile.example",
            HTTP_X_FORWARDED_PROTO="http",
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            "https://palworld.example.com/accounts/reset/",
            mail.outbox[0].body,
        )

    @override_settings(PUBLIC_SITE_URL="")
    def test_password_reset_fails_closed_without_canonical_origin(self):
        self.create_user(verified=True, approved=True)

        response = self.client.post(
            reverse("password_reset"),
            {"email": "member@example.com"},
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)
