from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.models import ConnectorBatch, UserProfile, VmMetricSample
from dashboard.vm_metrics import VM_METRICS


@override_settings(SITE_AUTH_REQUIRED=False, VM_DATA_STALE_SECONDS=180)
class VmApiTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        values = {
            "cpu.util_pct": 21.5,
            "memory.util_pct": 63.25,
            "load.1m": 0.42,
            "uptime_seconds": 86400,
            "filesystem.root.util_pct": 48,
            "network.rx_bps": 1200,
            "network.tx_bps": 800,
        }
        for metric, value in values.items():
            VmMetricSample.objects.create(
                metric=metric,
                value=value,
                source_clock=self.now,
            )

    def test_vm_snapshot_returns_latest_metrics_and_missing_list(self):
        response = self.client.get(reverse("vm-snapshot"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["status"]["available"])
        self.assertFalse(payload["status"]["stale"])
        self.assertTrue(payload["status"]["partial"])
        self.assertEqual(payload["metrics"]["cpu.util_pct"]["value"], 21.5)
        self.assertIn("docker.ping", payload["missing"])
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_vm_snapshot_marks_individual_stale_metrics_as_missing(self):
        VmMetricSample.objects.filter(metric="memory.util_pct").update(
            source_clock=self.now - timedelta(minutes=10)
        )

        payload = self.client.get(reverse("vm-snapshot")).json()

        self.assertFalse(payload["status"]["stale"])
        self.assertTrue(payload["status"]["partial"])
        self.assertIn("memory.util_pct", payload["missing"])
        self.assertNotIn("cpu.util_pct", payload["missing"])

    def test_vm_snapshot_supports_fresh_docker_only_telemetry(self):
        VmMetricSample.objects.all().delete()
        VmMetricSample.objects.create(
            metric="docker.containers.running",
            value=4,
            source_clock=self.now,
        )

        payload = self.client.get(reverse("vm-snapshot")).json()

        self.assertTrue(payload["status"]["available"])
        self.assertFalse(payload["status"]["stale"])
        self.assertTrue(payload["status"]["partial"])
        self.assertEqual(payload["metrics"]["docker.containers.running"]["value"], 4)

    def test_vm_history_samples_supported_ranges(self):
        VmMetricSample.objects.create(
            metric="cpu.util_pct",
            value=18,
            source_clock=self.now - timedelta(hours=1),
        )

        response = self.client.get(reverse("vm-history") + "?range=6h")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["series"]["cpu.util_pct"]), 2)
        self.assertEqual(
            self.client.get(reverse("vm-history") + "?range=30d").status_code,
            400,
        )

    def test_vm_page_renders_without_metrics_dependency(self):
        response = self.client.get(reverse("vm-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stato della VM")
        self.assertContains(response, "dashboard/js/vm.js")


@override_settings(
    SITE_AUTH_REQUIRED=True,
    SITE_ADMIN_USERS={"admin@example.com"},
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class ConnectorDiagnosticsTests(TestCase):
    def create_user(self, username, email, admin=False):
        user = get_user_model().objects.create_user(
            username=username,
            email=email,
            password="test-password",
        )
        UserProfile.objects.create(
            user=user,
            email_verified=True,
            approved=True,
        )
        if admin:
            self.assertEqual(email, "admin@example.com")
        return user

    def test_connector_diagnostics_are_admin_only(self):
        ConnectorBatch.objects.create(
            record_count=4,
            accepted=3,
            ignored=1,
            rejected=0,
            datasets=["metrics", "vm"],
            source_hosts=["vm-palworld"],
            ignored_items=["Unexpected item"],
        )
        VmMetricSample.objects.create(
            metric="cpu.util_pct",
            value=20,
            source_clock=timezone.now(),
        )
        member = self.create_user("member", "member@example.com")
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse("connector-status")).status_code, 403)

        admin = self.create_user("administrator", "admin@example.com", admin=True)
        self.client.force_login(admin)
        response = self.client.get(reverse("connector-status"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["batches_24h"], 1)
        self.assertEqual(payload["summary"]["records_24h"], 4)
        self.assertEqual(payload["batches"][0]["ignored_items"], ["Unexpected item"])
        self.assertEqual(payload["batches"][0]["source_hosts"], ["vm-palworld"])
        self.assertEqual(payload["vm"]["received"], ["cpu.util_pct"])
        self.assertEqual(len(payload["vm"]["missing"]), len(VM_METRICS) - 1)
        self.assertEqual(
            sorted(payload["datasets"]),
            ["info", "metrics", "players", "settings", "status"],
        )
        self.assertFalse(payload["datasets"]["status"]["received"])
