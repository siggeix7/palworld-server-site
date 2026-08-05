import logging

from django.test import SimpleTestCase

from dashboard.logging import RedactSensitivePathsFilter


class SensitivePathLoggingTests(SimpleTestCase):
    def test_redacts_account_tokens_from_formatted_log_messages(self):
        path_filter = RedactSensitivePathsFilter()
        for path in (
            "/accounts/verify/MQ/private-verification-token/",
            "/accounts/reset/MQ/private-reset-token/",
        ):
            with self.subTest(path=path):
                record = logging.LogRecord(
                    "django.request",
                    logging.WARNING,
                    __file__,
                    1,
                    "%s: %s",
                    ("Bad Request", path),
                    None,
                )
                self.assertTrue(path_filter.filter(record))
                message = record.getMessage()
                self.assertIn("/[redacted]/[redacted]/", message)
                self.assertNotIn("private-", message)

    def test_preserves_non_sensitive_paths(self):
        record = logging.LogRecord(
            "django.request",
            logging.WARNING,
            __file__,
            1,
            "Unauthorized: %s",
            ("/api/v1/session",),
            None,
        )
        RedactSensitivePathsFilter().filter(record)
        self.assertEqual(record.getMessage(), "Unauthorized: /api/v1/session")
