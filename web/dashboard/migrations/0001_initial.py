import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    operations = [
        migrations.CreateModel(
            name="LatestDataset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=32, unique=True)),
                ("payload", models.JSONField(default=dict)),
                ("source_clock", models.DateTimeField(db_index=True)),
                ("received_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["key"]},
        ),
        migrations.CreateModel(
            name="MetricSample",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_clock", models.DateTimeField(unique=True)),
                ("current_players", models.PositiveIntegerField(default=0)),
                ("max_players", models.PositiveIntegerField(default=0)),
                ("server_fps", models.FloatField(default=0)),
                ("server_fps_average", models.FloatField(default=0)),
                ("frame_time", models.FloatField(default=0)),
                ("world_days", models.PositiveIntegerField(default=0)),
                ("base_camps", models.PositiveIntegerField(default=0)),
                ("uptime", models.PositiveBigIntegerField(default=0)),
            ],
            options={"ordering": ["source_clock"]},
        ),
        migrations.CreateModel(
            name="Player",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.CharField(max_length=32, unique=True)),
                ("name", models.CharField(max_length=128)),
                ("account_name", models.CharField(blank=True, max_length=128)),
                ("first_seen", models.DateTimeField()),
                ("last_seen", models.DateTimeField(db_index=True)),
                ("level", models.PositiveIntegerField(default=0)),
                ("building_count", models.PositiveIntegerField(default=0)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="RuntimeState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=64, unique=True)),
                ("value", models.JSONField(default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="PlayerSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField(db_index=True)),
                ("last_seen", models.DateTimeField()),
                ("ended_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sessions", to="dashboard.player")),
            ],
            options={"ordering": ["-started_at"]},
        ),
        migrations.CreateModel(
            name="PositionSample",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_clock", models.DateTimeField(db_index=True)),
                ("x", models.FloatField()),
                ("y", models.FloatField()),
                ("ping", models.FloatField(default=0)),
                ("level", models.PositiveIntegerField(default=0)),
                ("building_count", models.PositiveIntegerField(default=0)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="positions", to="dashboard.player")),
            ],
            options={"ordering": ["source_clock"]},
        ),
        migrations.CreateModel(
            name="ServerEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("join", "Join"), ("leave", "Leave")], max_length=8)),
                ("source_clock", models.DateTimeField(db_index=True)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="dashboard.player")),
            ],
            options={"ordering": ["-source_clock"]},
        ),
        migrations.AddConstraint(
            model_name="playersession",
            constraint=models.UniqueConstraint(condition=models.Q(("ended_at__isnull", True)), fields=("player",), name="one_active_session_per_player"),
        ),
        migrations.AddConstraint(
            model_name="positionsample",
            constraint=models.UniqueConstraint(fields=("player", "source_clock"), name="unique_player_position_sample"),
        ),
    ]
