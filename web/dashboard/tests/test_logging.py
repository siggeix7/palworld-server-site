import logging

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from dashboard.logging import RedactSensitivePathsFilter, RequestIDFilter
from dashboard.middleware import RequestIDMiddleware


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

    def test_request_id_filter_adds_context_to_log_records(self):
        record = logging.LogRecord("django.request", logging.INFO, __file__, 1, "request", (), None)
        RequestIDFilter().filter(record)
        self.assertEqual(record.request_id, "-")

    def test_request_id_is_propagated_and_invalid_input_is_replaced(self):
        factory = RequestFactory()
        middleware = RequestIDMiddleware(lambda _request: HttpResponse("ok"))

        response = middleware(factory.get("/", HTTP_X_REQUEST_ID="trace-1234"))
        self.assertEqual(response.headers["X-Request-ID"], "trace-1234")

        response = middleware(factory.get("/", HTTP_X_REQUEST_ID="bad\nvalue"))
        generated = response.headers["X-Request-ID"]
        self.assertRegex(generated, r"^[0-9a-f]{32}$")
