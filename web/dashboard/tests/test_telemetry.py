import json
import logging
import os
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    SpanKind,
    Status,
    StatusCode,
    TraceFlags,
    TraceState,
    set_span_in_context,
)
from palworld_site import telemetry


class TelemetryTests(SimpleTestCase):
    def setUp(self):
        self.state = mock.patch.multiple(telemetry, _pid=None, _enabled=False)
        self.state.start()
        self.addCleanup(self.state.stop)

    def tracer(self):
        exporter = InMemorySpanExporter()
        provider = TracerProvider(
            resource=Resource({"service.name": "palworld-web", "secret": "PRIVATE_CANARY"}),
            shutdown_on_exit=False,
        )
        provider.add_span_processor(
            telemetry.SanitizingSpanProcessor(SimpleSpanProcessor(exporter))
        )
        self.addCleanup(provider.shutdown)
        return provider.get_tracer("test"), exporter

    @mock.patch("palworld_site.telemetry._configure_sdk")
    def test_disabled_by_default_and_no_exporters_created(self, configure_sdk):
        with mock.patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            self.assertFalse(telemetry.configure("web", django=True))
        configure_sdk.assert_not_called()

    @mock.patch("palworld_site.telemetry._configure_sdk")
    def test_configuration_is_per_process(self, configure_sdk):
        with mock.patch.dict(
            os.environ,
            {
                "OTEL_ENABLED": "true",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://receiver:4317",
                "OTEL_TRACES_SAMPLER_ARG": "0.25",
                "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
            },
        ):
            self.assertTrue(telemetry.configure("web", django=True))
            self.assertTrue(telemetry.configure("web", django=True))
        configure_sdk.assert_called_once_with("web", "http://receiver:4317", 0.25, django=True)
        with mock.patch("palworld_site.telemetry.os.getpid", return_value=os.getpid() + 1):
            self.assertFalse(telemetry.is_enabled())

    @mock.patch("palworld_site.telemetry._configure_sdk")
    def test_invalid_endpoint_or_sampler_is_fail_closed_without_logging_secrets(
        self, configure_sdk
    ):
        for endpoint, rate in [
            ("http://user:PRIVATE_CANARY@receiver:4317", "1"),
            ("http://receiver:4317/?token=PRIVATE_CANARY", "1"),
            ("http://receiver:4317/path/PRIVATE_CANARY", "1"),
            ("http://receiver:4317", "nan"),
            ("http://receiver:4317", "2"),
        ]:
            with (
                self.subTest(endpoint=endpoint, rate=rate),
                mock.patch.dict(
                    os.environ,
                    {
                        "OTEL_ENABLED": "true",
                        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
                        "OTEL_TRACES_SAMPLER_ARG": rate,
                    },
                ),
                mock.patch.object(telemetry, "_pid", None),
                self.assertLogs(telemetry.logger) as logs,
            ):
                self.assertFalse(telemetry.configure("web"))
                self.assertNotIn("PRIVATE_CANARY", " ".join(logs.output))
        configure_sdk.assert_not_called()

    def test_http_export_removes_urls_headers_events_links_and_status_messages(self):
        tracer, exporter = self.tracer()
        with tracer.start_as_current_span("PRIVATE_CANARY", kind=SpanKind.SERVER) as span:
            span.set_attributes(
                {
                    "http.method": "GET",
                    "http.status_code": 500,
                    "http.route": "accounts/reset/uid/PRIVATE_CANARY/",
                    "http.url": "https://user:PRIVATE_CANARY@host/?email=private@example.com",
                    "http.request.header.authorization": "Bearer PRIVATE_CANARY",
                    "user.email": "private@example.com",
                }
            )
            span.record_exception(ValueError("PRIVATE_CANARY"))
            span.add_link(span.get_span_context(), {"secret": "PRIVATE_CANARY"})
            span.set_status(Status(StatusCode.ERROR, "PRIVATE_CANARY"))
        exported = exporter.get_finished_spans()[0]
        serialized = json.dumps(json.loads(exported.to_json()))
        self.assertNotIn("PRIVATE_CANARY", serialized)
        self.assertNotIn("private@example.com", serialized)
        self.assertEqual(exported.attributes["http.route"], "accounts/token/[redacted]/")
        self.assertEqual(exported.status.status_code, StatusCode.ERROR)
        self.assertFalse(exported.events)
        self.assertFalse(exported.links)

    def test_database_export_keeps_operation_and_timing_without_sql_or_parameters(self):
        tracer, exporter = self.tracer()
        with tracer.start_as_current_span("SELECT PRIVATE_CANARY", kind=SpanKind.CLIENT) as span:
            span.set_attributes(
                {
                    "db.system": "postgresql",
                    "db.statement": "SELECT 'PRIVATE_CANARY'",
                    "db.parameters": ["PRIVATE_CANARY"],
                    "db.connection_string": "PRIVATE_CANARY",
                }
            )
        exported = exporter.get_finished_spans()[0]
        self.assertEqual(exported.name, "SQL SELECT")
        self.assertEqual(exported.attributes["db.operation.name"], "SELECT")
        self.assertNotIn("PRIVATE_CANARY", exported.to_json())
        self.assertGreaterEqual(exported.end_time, exported.start_time)

    def test_incoming_vendor_tracestate_is_removed_while_trace_ids_are_preserved(self):
        tracer, exporter = self.tracer()
        parent = SpanContext(
            trace_id=123,
            span_id=456,
            is_remote=True,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
            trace_state=TraceState([("vendor", "PRIVATE_CANARY")]),
        )
        with tracer.start_as_current_span(
            "request", context=set_span_in_context(NonRecordingSpan(parent)), kind=SpanKind.SERVER
        ):
            pass
        exported = exporter.get_finished_spans()[0]
        self.assertEqual(exported.context.trace_id, parent.trace_id)
        self.assertEqual(exported.parent.span_id, parent.span_id)
        self.assertFalse(exported.context.trace_state)
        self.assertFalse(exported.parent.trace_state)
        self.assertNotIn("PRIVATE_CANARY", exported.to_json())

    def test_only_structured_application_events_can_be_exported(self):
        event_filter = telemetry.SafeEventFilter()
        record = logging.makeLogRecord({"msg": "Login private@example.com", "args": ()})
        self.assertFalse(event_filter.filter(record))
        record = logging.makeLogRecord(
            {
                "msg": "HTTP request completed",
                "args": ("PRIVATE_CANARY",),
                "http.request.method": "GET",
                "http.response.status_code": 200,
                "user.email": "private@example.com",
                "url.full": "PRIVATE_CANARY",
                "exc_info": (ValueError, ValueError("PRIVATE_CANARY"), None),
            }
        )
        self.assertTrue(event_filter.filter(record))
        self.assertEqual(record.getMessage(), "HTTP request completed")
        self.assertNotIn("PRIVATE_CANARY", str(record.__dict__))
        self.assertNotIn("private@example.com", str(record.__dict__))
        self.assertEqual(record.__dict__["http.response.status_code"], 200)

    @mock.patch("palworld_site.telemetry.is_enabled", return_value=True)
    def test_metrics_failure_does_not_change_http_handling(self, enabled):
        del enabled
        counter = mock.Mock()
        counter.add.side_effect = RuntimeError("export unavailable")
        with mock.patch.dict(telemetry._instruments, {"requests": counter}):
            telemetry._response_hook(
                None,
                SimpleNamespace(method="GET"),
                SimpleNamespace(status_code=200),
            )

    @mock.patch("palworld_site.telemetry.is_enabled", return_value=True)
    def test_operation_reports_failure_without_exporting_exception_contents(self, enabled):
        del enabled
        tracer, exporter = self.tracer()
        instruments = {name: mock.Mock() for name in ("operations", "operation_duration")}
        with (
            mock.patch("palworld_site.telemetry.trace.get_tracer", return_value=tracer),
            mock.patch.dict(telemetry._instruments, instruments),
            mock.patch.object(telemetry.event_logger, "info"),
            self.assertRaisesRegex(ValueError, "PRIVATE_CANARY"),
            telemetry.operation("palworld.collect", dataset="metrics"),
        ):
            raise ValueError("PRIVATE_CANARY")
        exported = exporter.get_finished_spans()[0]
        self.assertEqual(exported.status.status_code, StatusCode.ERROR)
        self.assertEqual(exported.attributes["outcome"], "error")
        self.assertNotIn("PRIVATE_CANARY", exported.to_json())

    def test_telemetry_does_not_install_http_endpoints(self):
        from django.urls import Resolver404, resolve

        for path in ("/metrics", "/otel", "/v1/traces", "/v1/logs"):
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(path)
