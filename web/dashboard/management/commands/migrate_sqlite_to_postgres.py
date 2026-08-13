import json
import sqlite3
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connections, transaction
from django.utils.dateparse import parse_datetime
from psycopg.types.json import Jsonb

from dashboard.models import (
    AuthThrottle,
    GuildSnapshot,
    LatestDataset,
    MetricSample,
    Player,
    PlayerSession,
    PositionSample,
    RuntimeState,
    ServerEvent,
    UserProfile,
    WeeklyReportSchedule,
)


COPY_MODELS = (
    Group,
    get_user_model(),
    Session,
    LatestDataset,
    MetricSample,
    Player,
    RuntimeState,
    AuthThrottle,
    GuildSnapshot,
    UserProfile,
    PlayerSession,
    PositionSample,
    ServerEvent,
)


class Command(BaseCommand):
    help = "Copy the configured legacy SQLite database into an empty PostgreSQL database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm-empty-target",
            action="store_true",
            help="Confirm that this command may populate the empty PostgreSQL target",
        )

    def handle(self, *args, **options):
        if not options["confirm_empty_target"]:
            raise CommandError("--confirm-empty-target is required")
        if connections["default"].vendor != "postgresql":
            raise CommandError("the default database must be PostgreSQL")
        source_path = Path(settings.LEGACY_SQLITE_PATH)
        if not source_path.is_file():
            raise CommandError("LEGACY_SQLITE_PATH must point to a SQLite file")
        if "legacy" not in settings.DATABASES:
            raise CommandError("the legacy SQLite database alias is not configured")

        self._check_sqlite(source_path)
        self._check_target_empty()
        counts = {}
        with transaction.atomic(using="default"):
            self._ensure_auth_metadata()
            WeeklyReportSchedule.objects.using("default").all().delete()
            for model in COPY_MODELS:
                if model in {Group, Session}:
                    model.objects.using("default").all().delete()
                counts[model._meta.db_table] = self._copy_model(model)
            self._copy_many_to_many()
            counts.update(self._copy_obsolete_tables(source_path))
            self._reset_sequences()
            WeeklyReportSchedule.objects.using("default").get_or_create(id=1)
            self._verify_counts(counts)

        with connections["default"].cursor() as cursor:
            cursor.execute("ANALYZE")
        copied = sum(counts.values())
        self.stdout.write(
            self.style.SUCCESS(
                f"SQLite migration completed: {copied} rows copied and verified"
            )
        )

    def _check_sqlite(self, source_path):
        uri = f"file:{source_path}?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True) as source:
            result = source.execute("PRAGMA quick_check").fetchone()
            if result != ("ok",):
                raise CommandError("SQLite quick_check failed")
            violations = source.execute("PRAGMA foreign_key_check").fetchone()
            if violations is not None:
                raise CommandError("SQLite foreign_key_check failed")

    def _check_target_empty(self):
        ignored = {"auth.Group", "sessions.Session"}
        populated = [
            model._meta.label
            for model in COPY_MODELS
            if model._meta.label not in ignored
            if model.objects.using("default").exists()
        ]
        if populated:
            raise CommandError(
                "PostgreSQL target is not empty: " + ", ".join(populated)
            )

    def _copy_model(self, model):
        fields = list(model._meta.local_concrete_fields)
        field_names = [field.attname for field in fields]
        source_rows = model.objects.using("legacy").order_by(model._meta.pk.attname)
        objects = []
        for source in source_rows.iterator(chunk_size=1000):
            objects.append(
                model(**{field_name: getattr(source, field_name) for field_name in field_names})
            )
            if len(objects) == 1000:
                model.objects.using("default").bulk_create(objects, batch_size=1000)
                objects.clear()
        if objects:
            model.objects.using("default").bulk_create(objects, batch_size=1000)
        return source_rows.count()

    def _ensure_auth_metadata(self):
        target_types = {
            (content_type.app_label, content_type.model): content_type
            for content_type in ContentType.objects.using("default").all()
        }
        for source_type in ContentType.objects.using("legacy").all():
            identity = (source_type.app_label, source_type.model)
            if identity not in target_types:
                target_types[identity] = ContentType.objects.using("default").create(
                    app_label=source_type.app_label,
                    model=source_type.model,
                )

        target_permissions = {
            (
                permission.content_type.app_label,
                permission.content_type.model,
                permission.codename,
            )
            for permission in Permission.objects.using("default").select_related(
                "content_type"
            )
        }
        for source_permission in Permission.objects.using("legacy").select_related(
            "content_type"
        ):
            identity = (
                source_permission.content_type.app_label,
                source_permission.content_type.model,
                source_permission.codename,
            )
            if identity in target_permissions:
                continue
            Permission.objects.using("default").create(
                content_type=target_types[identity[:2]],
                codename=source_permission.codename,
                name=source_permission.name,
            )
            target_permissions.add(identity)

    def _copy_many_to_many(self):
        User = get_user_model()
        for model in (User.groups.through,):
            fields = list(model._meta.local_concrete_fields)
            field_names = [field.attname for field in fields]
            objects = [
                model(**{name: getattr(source, name) for name in field_names})
                for source in model.objects.using("legacy").all().iterator(chunk_size=1000)
            ]
            model.objects.using("default").bulk_create(objects, batch_size=1000)

        target_permissions = {
            (
                permission.content_type.app_label,
                permission.content_type.model,
                permission.codename,
            ): permission.id
            for permission in Permission.objects.using("default").select_related("content_type")
        }
        for model, owner_field in (
            (Group.permissions.through, "group_id"),
            (User.user_permissions.through, "user_id"),
        ):
            objects = []
            source_rows = model.objects.using("legacy").select_related(
                "permission__content_type"
            )
            for source in source_rows.iterator(chunk_size=1000):
                permission = source.permission
                identity = (
                    permission.content_type.app_label,
                    permission.content_type.model,
                    permission.codename,
                )
                objects.append(
                    model(
                        **{
                            model._meta.pk.attname: source.pk,
                            owner_field: getattr(source, owner_field),
                            "permission_id": target_permissions[identity],
                        }
                    )
                )
            model.objects.using("default").bulk_create(objects, batch_size=1000)

    def _copy_obsolete_tables(self, source_path):
        specs = {
            "dashboard_connectorbatch": {
                "json": {"datasets", "source_hosts", "ignored_items"},
                "datetime": {"received_at"},
            },
            "dashboard_vmmetricsample": {
                "json": set(),
                "datetime": {"source_clock", "received_at"},
            },
        }
        counts = {}
        uri = f"file:{source_path}?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True) as source:
            source.row_factory = sqlite3.Row
            existing = {
                row[0]
                for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            with connections["default"].cursor() as target:
                for table, spec in specs.items():
                    if table not in existing:
                        continue
                    rows = list(source.execute(f'SELECT * FROM "{table}" ORDER BY id'))
                    if not rows:
                        counts[table] = 0
                        continue
                    columns = rows[0].keys()
                    placeholders = ", ".join(["%s"] * len(columns))
                    column_sql = ", ".join(f'"{column}"' for column in columns)
                    values = []
                    for row in rows:
                        converted = []
                        for column in columns:
                            value = row[column]
                            if value is not None and column in spec["json"]:
                                value = Jsonb(json.loads(value))
                            elif value is not None and column in spec["datetime"]:
                                value = parse_datetime(value)
                            converted.append(value)
                        values.append(converted)
                    target.executemany(
                        f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})',
                        values,
                    )
                    counts[table] = len(rows)
        return counts

    def _reset_sequences(self):
        models = list(COPY_MODELS) + [
            Group.permissions.through,
            get_user_model().groups.through,
            get_user_model().user_permissions.through,
        ]
        statements = connections["default"].ops.sequence_reset_sql(no_style(), models)
        with connections["default"].cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    def _verify_counts(self, expected):
        with connections["default"].cursor() as cursor:
            for table, source_count in expected.items():
                cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                target_count = cursor.fetchone()[0]
                if target_count != source_count:
                    raise CommandError(
                        f"row count mismatch for {table}: {source_count} != {target_count}"
                    )
