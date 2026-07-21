from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0004_userprofile_admin_notified_at")]

    operations = [
        migrations.CreateModel(
            name="ConnectorBatch",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("received_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("record_count", models.PositiveIntegerField(default=0)),
                ("accepted", models.PositiveIntegerField(default=0)),
                ("ignored", models.PositiveIntegerField(default=0)),
                ("rejected", models.PositiveIntegerField(default=0)),
                ("datasets", models.JSONField(default=list)),
                ("source_hosts", models.JSONField(default=list)),
                ("ignored_items", models.JSONField(default=list)),
            ],
            options={"ordering": ["-received_at"]},
        ),
        migrations.CreateModel(
            name="VmMetricSample",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("metric", models.CharField(db_index=True, max_length=64)),
                ("source_clock", models.DateTimeField(db_index=True)),
                ("value", models.FloatField()),
                ("received_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["source_clock"],
                "indexes": [
                    models.Index(
                        fields=["metric", "-source_clock"],
                        name="vm_metric_latest_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("metric", "source_clock"),
                        name="unique_vm_metric_sample",
                    )
                ],
            },
        ),
    ]
