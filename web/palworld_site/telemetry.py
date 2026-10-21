"""Opt-in, bounded OpenTelemetry export with an explicit data allowlist."""

import logging
import math
import os
import re
import time
import uuid
from contextlib import contextmanager
from urllib.parse import urlsplit

from opentelemetry import metrics, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

logger = logging.getLogger(__name__)
event_logger = logging.getLogger("palworld.telemetry")
_pid = None
_enabled = False
_instruments = {}

ROLES = {"web", "ingest", "collector", "retention", "scheduler"}
DATASETS = {"status", "info", "metrics", "players", "settings", "game_data"}
OPERATIONS = {"palworld.collect", "palworld.retention", "palworld.weekly_report"}
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "CONNECT", "TRACE"}
SQL_OPERATIONS = {
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "SAVEPOINT",
    "RELEASE",
    "WITH",
    "EXPLAIN",
    "SET",
    "SHOW",
    "CREATE",
    "ALTER",
    "DROP",
}
METRIC_ATTRIBUTES = {
    "http.method",
    "http.request.method",
    "http.status_code",
    "http.response.status_code",
    "operation",
    "dataset",
    "outcome",
}
EVENT_MESSAGES = {"HTTP request completed", "Background operation completed"}
_LOG_RECORD_KEYS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def _safe_label(value, default="unknown"):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.+-]{1,96}", value)
        else default
    )


def safe_route(value):
    """Only accept Django route templates, never raw request URLs or query strings."""
    if not isinstance(value, str) or len(value) > 180:
        return "unresolved"
    if not re.fullmatch(r"[A-Za-z0-9_/<>:.-]*", value):
        return "unresolved"
    if re.search(r"(?:^|/)accounts/(?:verify|reset)/", value):
        return "accounts/token/[redacted]/"
    return value or "/"


def _http_attributes(attributes):
    method = attributes.get("http.request.method", attributes.get("http.method", "OTHER"))
    method = method if method in METHODS else "OTHER"
    result = {"http.request.method": method, "http.method": method}
    status = attributes.get("http.response.status_code", attributes.get("http.status_code"))
    if isinstance(status, int) and 100 <= status <= 599:
        result.update({"http.response.status_code": status, "http.status_code": status})
    return result


def sanitized_span(span):
    attributes = span.attributes or {}
    database = attributes.get("db.system.name", attributes.get("db.system"))
    if database in {"postgresql", "postgres", "sqlite"}:
        operation = attributes.get("db.operation.name", attributes.get("db.operation", ""))
        if not operation:
            statement = attributes.get("db.query.text", attributes.get("db.statement", ""))
            match = re.match(r"\s*([A-Za-z]+)", statement) if isinstance(statement, str) else None
            operation = match.group(1).upper() if match else "OTHER"
        operation = operation if operation in SQL_OPERATIONS else "OTHER"
        safe = {"db.system": database, "db.system.name": database, "db.operation.name": operation}
        name = f"SQL {operation}"
    elif span.kind in {SpanKind.SERVER, SpanKind.CLIENT}:
        safe = _http_attributes(attributes)
        name = f"HTTP {safe['http.request.method']}"
        if span.kind == SpanKind.SERVER:
            safe["http.route"] = safe_route(attributes.get("http.route"))
            name += f" {safe['http.route']}"
    else:
        name = span.name if span.name in OPERATIONS else "palworld.operation"
        safe = {"operation": name}
        if attributes.get("dataset") in DATASETS:
            safe["dataset"] = attributes["dataset"]
        if attributes.get("outcome") in {"ok", "error"}:
            safe["outcome"] = attributes["outcome"]

    resource = Resource(
        {
            key: _safe_label(value)
            for key, value in span.resource.attributes.items()
            if key
            in {"service.name", "service.namespace", "service.version", "service.instance.id"}
        }
    )
    return ReadableSpan(
        name=name,
        context=span.context,
        parent=span.parent,
        resource=resource,
        attributes=safe,
        events=(),
        links=(),
        kind=span.kind,
        status=Status(span.status.status_code),
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class SanitizingSpanProcessor(SpanProcessor):
    """Sanitize before spans enter the asynchronous export queue."""

    def __init__(self, processor):
        self.processor = processor

    def on_start(self, span, parent_context=None):
        return None

    def on_end(self, span):
        try:
            self.processor.on_end(sanitized_span(span))
        except Exception:
            # Export failures must not change request handling or disclose span contents.
            return

    def shutdown(self):
        return self.processor.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self.processor.force_flush(timeout_millis)


class SafeEventFilter(logging.Filter):
    def filter(self, record):
        if not isinstance(record.msg, str) or record.msg not in EVENT_MESSAGES:
            return False
        record.args = ()
        record.exc_info = record.exc_text = record.stack_info = None
        for key in set(record.__dict__) - _LOG_RECORD_KEYS - METRIC_ATTRIBUTES:
            del record.__dict__[key]
        for key in METRIC_ATTRIBUTES & record.__dict__.keys():
            value = record.__dict__[key]
            if key in {"http.method", "http.request.method"}:
                record.__dict__[key] = value if value in METHODS else "OTHER"
            elif key in {"http.status_code", "http.response.status_code"}:
                if not isinstance(value, int) or not 100 <= value <= 599:
                    del record.__dict__[key]
            elif (
                (key == "dataset" and value not in DATASETS)
                or (key == "outcome" and value not in {"ok", "error"})
                or (key == "operation" and value not in OPERATIONS)
            ):
                del record.__dict__[key]
        return True


def is_enabled():
    return _enabled and _pid == os.getpid()


def configure(role, *, django=False):
    """Called in each WSGI worker or long-running management-command process."""
    global _pid, _enabled
    if _pid == os.getpid():
        return is_enabled()
    _pid = os.getpid()
    _enabled = False
    if os.getenv("OTEL_ENABLED", "false").lower() != "true":
        return False
    try:
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        parsed = urlsplit(endpoint)
        if (
            role not in ROLES
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or not parsed.port
            or os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc") != "grpc"
        ):
            raise ValueError("Invalid telemetry configuration")
        sample_rate = float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "0.1"))
        if not math.isfinite(sample_rate) or not 0 <= sample_rate <= 1:
            raise ValueError("Invalid sampling rate")
        _configure_sdk(role, endpoint, sample_rate, django=django)
        _enabled = True
    except Exception:
        logger.warning("OpenTelemetry initialization unavailable; telemetry disabled")
    return _enabled


def _configure_sdk(role, endpoint, sample_rate, *, django):
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.propagate import set_global_textmap
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.metrics.view import View
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    resource = Resource(
        {
            "service.name": f"{_safe_label(os.getenv('OTEL_SERVICE_NAME', 'palworld'))}-{role}",
            "service.namespace": "palworld",
            "service.version": _safe_label(os.getenv("APP_VERSION", "dev")),
            "service.instance.id": uuid.uuid4().hex,
        }
    )
    options = {"endpoint": endpoint, "insecure": urlsplit(endpoint).scheme == "http", "timeout": 2}
    tracer_provider = TracerProvider(
        resource=resource, sampler=ParentBased(TraceIdRatioBased(sample_rate))
    )
    tracer_provider.add_span_processor(
        SanitizingSpanProcessor(
            BatchSpanProcessor(
                OTLPSpanExporter(**options),
                max_queue_size=512,
                max_export_batch_size=128,
                schedule_delay_millis=5000,
                export_timeout_millis=2000,
            )
        )
    )
    trace.set_tracer_provider(tracer_provider)
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(**options),
                export_interval_millis=30000,
                export_timeout_millis=5000,
            )
        ],
        views=[View(instrument_name="*", attribute_keys=METRIC_ATTRIBUTES)],
    )
    metrics.set_meter_provider(meter_provider)
    log_provider = LoggerProvider(resource=resource)
    log_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(**options),
            max_queue_size=512,
            max_export_batch_size=128,
            schedule_delay_millis=5000,
            export_timeout_millis=2000,
        )
    )
    handler = LoggingHandler(level=logging.INFO, logger_provider=log_provider)
    handler.addFilter(SafeEventFilter())
    event_logger.handlers = [handler]
    event_logger.setLevel(logging.INFO)
    event_logger.propagate = False

    # Only W3C trace context is propagated; arbitrary incoming baggage is not exported.
    set_global_textmap(TraceContextTextMapPropagator())
    PsycopgInstrumentor().instrument(tracer_provider=tracer_provider, enable_commenter=False)
    # Metrics use only the bounded attributes assembled below, not raw HTTP labels.
    quiet_meter_provider = metrics.NoOpMeterProvider()
    RequestsInstrumentor().instrument(
        tracer_provider=tracer_provider, meter_provider=quiet_meter_provider
    )
    if django:
        from opentelemetry.instrumentation.django import DjangoInstrumentor

        DjangoInstrumentor().instrument(
            tracer_provider=tracer_provider,
            meter_provider=quiet_meter_provider,
            excluded_urls="/healthz/,/static/",
            request_hook=_request_hook,
            response_hook=_response_hook,
        )
    meter = meter_provider.get_meter("palworld.telemetry")
    _instruments.update(
        {
            "requests": meter.create_counter("palworld.http.requests", unit="{request}"),
            "duration": meter.create_histogram("palworld.http.duration", unit="s"),
            "operations": meter.create_counter("palworld.operations", unit="{operation}"),
            "operation_duration": meter.create_histogram("palworld.operation.duration", unit="s"),
        }
    )


def _request_hook(span, request):
    del span
    request._palworld_otel_started = time.monotonic()


def _response_hook(span, request, response):
    if not is_enabled():
        return
    try:
        _record_response(span, request, response)
    except Exception:
        return


def _record_response(span, request, response):
    attributes = _http_attributes(
        {
            "http.request.method": request.method,
            "http.response.status_code": response.status_code,
        }
    )
    _instruments["requests"].add(1, attributes)
    started = getattr(request, "_palworld_otel_started", None)
    if started is not None:
        _instruments["duration"].record(max(0, time.monotonic() - started), attributes)
    if span and span.is_recording():
        with trace.use_span(span, end_on_exit=False):
            event_logger.info("HTTP request completed", extra=attributes)


class Observation:
    failed = False

    def fail(self):
        self.failed = True


@contextmanager
def operation(name, *, dataset=None):
    observation = Observation()
    if not is_enabled() or name not in OPERATIONS:
        yield observation
        return
    attributes = {"operation": name}
    if dataset in DATASETS:
        attributes["dataset"] = dataset
    started = time.monotonic()
    with trace.get_tracer("palworld.telemetry").start_as_current_span(
        name,
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield observation
        except Exception:
            observation.fail()
            raise
        finally:
            try:
                attributes["outcome"] = "error" if observation.failed else "ok"
                span.set_attribute("outcome", attributes["outcome"])
                if observation.failed:
                    span.set_status(Status(StatusCode.ERROR))
                _instruments["operations"].add(1, attributes)
                _instruments["operation_duration"].record(time.monotonic() - started, attributes)
                if span.is_recording():
                    event_logger.info("Background operation completed", extra=attributes)
            except Exception:
                pass
