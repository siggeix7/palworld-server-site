from unittest import mock
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
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
        accepted_terms=True,
    ):
        user = get_user_model().objects.create_user(
            username=username,
            email=email,
            password=self.password,
        )
        profile_kwargs = dict(
            user=user,
            email_verified=verified,
            approved=approved,
            must_change_password=must_change_password,
        )
        if accepted_terms:
            profile_kwargs["terms_version"] = settings.CURRENT_TERMS_VERSION
            profile_kwargs["terms_accepted_at"] = timezone.now()
        UserProfile.objects.create(**profile_kwargs)
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

    def test_approved_account_fetches_credentials_from_non_cacheable_api(self):
        user = self.create_user(verified=True, approved=True)
        self.client.force_login(user)

        page_response = self.client.get(reverse("access"))
        self.assertEqual(page_response.status_code, 200)
        self.assertNotContains(page_response, "game-server-secret")

        response = self.client.get(reverse("server-access-api"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["host"], "play.example.com")
        self.assertEqual(response.json()["password"], "game-server-secret")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])

    def test_register_page_shows_palworld_username_warning(self):
        response = self.client.get(reverse("register"))
        self.assertContains(response, "esattamente")
        self.assertContains(response, "Palworld")

    def test_approved_user_can_change_username(self):
        user = self.create_user(verified=True, approved=True)
        self.client.force_login(user)
        response = self.client.post(
            reverse("change-username"),
            {"new_username": "NewPalworldName"},
        )
        self.assertRedirects(response, reverse("change-username"))
        user.refresh_from_db()
        self.assertEqual(user.username, "NewPalworldName")

    def test_username_change_rejects_duplicates(self):
        self.create_user(username="taken", email="taken@example.com", verified=True, approved=True)
        user = self.create_user(username="other", email="other@example.com", verified=True, approved=True)
        self.client.force_login(user)
        response = self.client.post(
            reverse("change-username"),
            {"new_username": "Taken"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Esiste già")
        user.refresh_from_db()
        self.assertEqual(user.username, "other")

    def test_registration_creates_pending_profile_and_sends_verification(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "NewMember",
                "email": "NewMember@Example.com",
                "password1": self.password,
                "password2": self.password,
                "accept_terms": "1",
                "terms_version": settings.CURRENT_TERMS_VERSION,
            },
        )

        self.assertRedirects(response, reverse("registration-done"))
        user = get_user_model().objects.get(username="NewMember")
        self.assertEqual(user.email, "newmember@example.com")
        self.assertFalse(user.site_profile.email_verified)
        self.assertFalse(user.site_profile.approved)
        self.assertIsNotNone(user.site_profile.terms_accepted_at)
        self.assertEqual(
            user.site_profile.terms_version,
            settings.CURRENT_TERMS_VERSION,
        )
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
                "accept_terms": "1",
                "terms_version": settings.CURRENT_TERMS_VERSION,
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
                "accept_terms": "on",
                "terms_version": settings.CURRENT_TERMS_VERSION,
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
                "accept_terms": "on",
                "terms_version": settings.CURRENT_TERMS_VERSION,
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
                "accept_terms": "on",
                "terms_version": settings.CURRENT_TERMS_VERSION,
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
        self.assertRedirects(
            self.client.get(reverse("members")),
            reverse("pending-approval"),
            fetch_redirect_response=False,
        )

    @override_settings(SITE_ADMIN_USERS={"administrator"})
    def test_registration_cannot_claim_configured_admin_username(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "Administrator",
                "email": "attacker@example.net",
                "password1": self.password,
                "password2": self.password,
                "accept_terms": "on",
                "terms_version": settings.CURRENT_TERMS_VERSION,
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
        self.assertRedirects(
            self.client.get(reverse("members")),
            reverse("pending-approval"),
            fetch_redirect_response=False,
        )

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

        self.assertRedirects(
            response,
            reverse("home"),
            fetch_redirect_response=False,
        )

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

    def test_terms_page_is_public_and_includes_version_and_date(self):
        response = self.client.get(reverse("terms"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Condizioni d'uso e informativa privacy")
        self.assertContains(response, settings.CURRENT_TERMS_VERSION)
        self.assertContains(response, settings.CURRENT_TERMS_EFFECTIVE_DATE)
        response = self.create_user(verified=True, approved=True)
        self.client.force_login(response)
        authed_response = self.client.get(reverse("terms"))
        self.assertEqual(authed_response.status_code, 200)
        self.assertIn("no-store", authed_response.headers["Cache-Control"])

    def test_register_rejects_missing_terms_acceptance(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "NoTermsUser",
                "email": "noterms@example.com",
                "password1": self.password,
                "password2": self.password,
                "terms_version": settings.CURRENT_TERMS_VERSION,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="NoTermsUser").exists())
        self.assertContains(response, "accetto")

    def test_register_rejects_a_stale_terms_version(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "StaleTermsUser",
                "email": "stale@example.com",
                "password1": self.password,
                "password2": self.password,
                "accept_terms": "on",
                "terms_version": "2026-07-27",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "condizioni sono cambiate")
        self.assertFalse(
            get_user_model().objects.filter(username="StaleTermsUser").exists()
        )

    def test_existing_user_without_terms_is_redirected_on_first_login(self):
        user = self.create_user(verified=True, approved=True, accepted_terms=False)
        self.client.force_login(user)
        response = self.client.get(reverse("home"))
        self.assertRedirects(
            response,
            f"{reverse('accept-terms')}?{urlencode({'next': reverse('home')})}",
            fetch_redirect_response=False,
        )

    def test_existing_user_login_redirects_directly_to_current_terms(self):
        self.create_user(verified=True, approved=True, accepted_terms=False)
        response = self.client.post(
            reverse("login"),
            {"username": "member", "password": self.password},
        )
        self.assertRedirects(
            response,
            f"{reverse('accept-terms')}?{urlencode({'next': reverse('home')})}",
            fetch_redirect_response=False,
        )

    def test_admin_login_redirects_directly_to_current_terms(self):
        admin = self.create_user(
            username="administrator",
            email="admin@example.com",
            verified=True,
            accepted_terms=False,
        )
        get_user_profile(admin)
        response = self.client.post(
            reverse("login"),
            {"username": "admin@example.com", "password": self.password},
        )
        self.assertRedirects(
            response,
            f"{reverse('accept-terms')}?{urlencode({'next': reverse('home')})}",
            fetch_redirect_response=False,
        )

    def test_terms_gate_covers_protected_account_routes(self):
        user = self.create_user(verified=True, approved=True, accepted_terms=False)
        self.client.force_login(user)
        path = reverse("change-username")
        self.assertRedirects(
            self.client.get(path),
            f"{reverse('accept-terms')}?{urlencode({'next': path})}",
            fetch_redirect_response=False,
        )

    def test_api_request_returns_403_when_terms_pending(self):
        user = self.create_user(verified=True, approved=True, accepted_terms=False)
        self.client.force_login(user)
        response = self.client.get(reverse("snapshot"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "terms acceptance required"})

    def test_accept_terms_post_stamps_profile_and_redirects_home(self):
        user = self.create_user(verified=True, approved=True, accepted_terms=False)
        self.client.force_login(user)
        response = self.client.post(
            reverse("accept-terms"),
            {
                "accept_terms": "on",
                "terms_version": settings.CURRENT_TERMS_VERSION,
            },
        )
        self.assertRedirects(response, reverse("home"))
        user.site_profile.refresh_from_db()
        self.assertEqual(user.site_profile.terms_version, settings.CURRENT_TERMS_VERSION)
        self.assertIsNotNone(user.site_profile.terms_accepted_at)

    def test_get_accept_terms_page_shows_form_for_requires_acceptance_user(self):
        user = self.create_user(verified=True, approved=True, accepted_terms=False)
        self.client.force_login(user)
        response = self.client.get(reverse("accept-terms"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Accetta e prosegui")
        self.assertContains(response, settings.CURRENT_TERMS_VERSION)

    def test_accept_terms_redirects_already_compliant_user_to_home(self):
        user = self.create_user(verified=True, approved=True)
        self.client.force_login(user)
        response = self.client.get(reverse("accept-terms"))
        self.assertRedirects(response, reverse("home"))

    def test_accept_terms_does_not_stamp_when_checkbox_not_set(self):
        user = self.create_user(verified=True, approved=True, accepted_terms=False)
        self.client.force_login(user)
        response = self.client.post(
            reverse("accept-terms"),
            {"terms_version": settings.CURRENT_TERMS_VERSION},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Accetta e prosegui")
        user.site_profile.refresh_from_db()
        self.assertEqual(user.site_profile.terms_version, "")
        self.assertIsNone(user.site_profile.terms_accepted_at)

    def test_terms_pending_user_can_still_logout(self):
        user = self.create_user(verified=True, approved=True, accepted_terms=False)
        self.client.force_login(user)
        self.assertIsNotNone(self.client.session.get("_auth_user_id"))
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        self.assertIsNone(self.client.session.get("_auth_user_id"))

    def test_configured_admin_must_accept_terms_before_managing_members(self):
        admin = self.create_user(
            username="administrator",
            email="admin@example.com",
            verified=True,
            accepted_terms=False,
        )
        get_user_profile(admin)
        self.client.force_login(admin)
        members_response = self.client.get(reverse("members"))
        self.assertRedirects(
            members_response,
            f"{reverse('accept-terms')}?{urlencode({'next': reverse('members')})}",
            fetch_redirect_response=False,
        )
        self.client.post(
            reverse("accept-terms"),
            {
                "accept_terms": "on",
                "terms_version": settings.CURRENT_TERMS_VERSION,
            },
        )
        admin.site_profile.refresh_from_db()
        self.assertEqual(admin.site_profile.terms_version, settings.CURRENT_TERMS_VERSION)
        response = self.client.get(reverse("members"))
        self.assertEqual(response.status_code, 200)

    @override_settings(CURRENT_TERMS_VERSION="2099-01-01")
    def test_terms_version_bump_requires_reacceptance(self):
        user = get_user_model().objects.create_user(
            username="bumpmember",
            email="bump@example.com",
            password=self.password,
        )
        UserProfile.objects.create(
            user=user,
            email_verified=True,
            approved=True,
            terms_version="2026-07-27",
            terms_accepted_at=timezone.now(),
        )
        self.client.force_login(user)
        response = self.client.get(reverse("home"))
        self.assertRedirects(
            response,
            f"{reverse('accept-terms')}?{urlencode({'next': reverse('home')})}",
            fetch_redirect_response=False,
        )
        self.client.post(
            reverse("accept-terms"),
            {"accept_terms": "on", "terms_version": "2099-01-01"},
        )
        user.site_profile.refresh_from_db()
        self.assertEqual(user.site_profile.terms_version, "2099-01-01")
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_stale_terms_form_cannot_accept_a_newer_version(self):
        user = self.create_user(verified=True, approved=True, accepted_terms=False)
        self.client.force_login(user)
        response = self.client.post(
            reverse("accept-terms"),
            {"accept_terms": "on", "terms_version": "2026-07-27"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "condizioni sono cambiate")
        self.assertContains(response, settings.CURRENT_TERMS_VERSION)
        user.site_profile.refresh_from_db()
        self.assertEqual(user.site_profile.terms_version, "")
        self.assertIsNone(user.site_profile.terms_accepted_at)

    def test_accept_terms_requires_csrf(self):
        user = self.create_user(verified=True, approved=True, accepted_terms=False)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)
        response = csrf_client.post(
            reverse("accept-terms"),
            {
                "accept_terms": "on",
                "terms_version": settings.CURRENT_TERMS_VERSION,
            },
        )
        self.assertEqual(response.status_code, 403)
        user.site_profile.refresh_from_db()
        self.assertEqual(user.site_profile.terms_version, "")

        page = csrf_client.get(reverse("accept-terms"))
        token = page.cookies["csrftoken"].value
        response = csrf_client.post(
            reverse("accept-terms"),
            {
                "csrfmiddlewaretoken": token,
                "accept_terms": "on",
                "terms_version": settings.CURRENT_TERMS_VERSION,
            },
        )
        self.assertRedirects(response, reverse("home"))
        user.site_profile.refresh_from_db()
        self.assertEqual(user.site_profile.terms_version, settings.CURRENT_TERMS_VERSION)

    def test_accept_terms_rejects_external_next_redirect(self):
        user = self.create_user(verified=True, approved=True, accepted_terms=False)
        self.client.force_login(user)
        response = self.client.post(
            f"{reverse('accept-terms')}?next=https%3A%2F%2Fevil.example%2F",
            {
                "accept_terms": "on",
                "terms_version": settings.CURRENT_TERMS_VERSION,
                "next": "https://evil.example/",
            },
        )
        self.assertRedirects(response, reverse("home"))

    def test_password_change_precedes_terms_acceptance(self):
        user = self.create_user(
            verified=True,
            approved=True,
            must_change_password=True,
            accepted_terms=False,
        )
        self.client.force_login(user)
        self.assertRedirects(
            self.client.get(reverse("home")),
            reverse("password_change"),
            fetch_redirect_response=False,
        )
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": self.password,
                "new_password1": "A-new-valid-test-password-963!",
                "new_password2": "A-new-valid-test-password-963!",
            },
        )
        self.assertRedirects(
            response,
            reverse("home"),
            fetch_redirect_response=False,
        )
        user.site_profile.refresh_from_db()
        self.assertFalse(user.site_profile.must_change_password)
        self.assertEqual(user.site_profile.terms_version, "")
        self.assertRedirects(
            self.client.get(reverse("home")),
            f"{reverse('accept-terms')}?{urlencode({'next': reverse('home')})}",
            fetch_redirect_response=False,
        )

    @override_settings(CURRENT_TERMS_VERSION="2099-admin")
    def test_admin_with_an_existing_session_must_reaccept_new_terms(self):
        admin = get_user_model().objects.create_user(
            username="administrator",
            email="admin@example.com",
            password=self.password,
        )
        UserProfile.objects.create(
            user=admin,
            email_verified=True,
            approved=True,
            terms_version="2026-07-29",
            terms_accepted_at=timezone.now(),
        )
        self.client.force_login(admin)
        for route in ("home", "members", "admin-panel"):
            with self.subTest(route=route):
                path = reverse(route)
                self.assertRedirects(
                    self.client.get(path),
                    f"{reverse('accept-terms')}?{urlencode({'next': path})}",
                    fetch_redirect_response=False,
                )
