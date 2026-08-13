import datetime

from django.db import migrations, models


def create_default_schedule(apps, schema_editor):
    schedule = apps.get_model("dashboard", "WeeklyReportSchedule")
    schedule.objects.get_or_create(
        id=1,
        defaults={
            "enabled": True,
            "weekday": 0,
            "run_time": datetime.time(8, 0),
            "timezone": "Europe/Rome",
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0011_player_ip_address_and_observed_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="WeeklyReportSchedule",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("enabled", models.BooleanField(default=True)),
                ("weekday", models.PositiveSmallIntegerField(default=0)),
                ("run_time", models.TimeField(default=datetime.time(8, 0))),
                ("timezone", models.CharField(default="Europe/Rome", max_length=64)),
                ("next_run_at", models.DateTimeField(blank=True, null=True)),
                ("last_scheduled_for", models.DateTimeField(blank=True, null=True)),
                ("last_started_at", models.DateTimeField(blank=True, null=True)),
                ("last_finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_status",
                    models.CharField(
                        choices=[
                            ("never", "Never"),
                            ("running", "Running"),
                            ("success", "Success"),
                            ("failed", "Failed"),
                            ("interrupted", "Interrupted"),
                        ],
                        default="never",
                        max_length=16,
                    ),
                ),
                ("last_error", models.CharField(blank=True, default="", max_length=64)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="weeklyreportschedule",
            constraint=models.CheckConstraint(
                condition=models.Q(("id", 1)),
                name="weekly_report_schedule_singleton",
            ),
        ),
        migrations.AddConstraint(
            model_name="weeklyreportschedule",
            constraint=models.CheckConstraint(
                condition=models.Q(("weekday__gte", 0), ("weekday__lte", 6)),
                name="weekly_report_schedule_valid_weekday",
            ),
        ),
        migrations.RunPython(create_default_schedule, migrations.RunPython.noop),
    ]
