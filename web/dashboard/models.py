from django.conf import settings
from django.db import models


class LatestDataset(models.Model):
    key = models.CharField(max_length=32, unique=True)
    payload = models.JSONField(default=dict)
    source_clock = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]


class MetricSample(models.Model):
    source_clock = models.DateTimeField(unique=True)
    current_players = models.PositiveIntegerField(default=0)
    max_players = models.PositiveIntegerField(default=0)
    server_fps = models.FloatField(default=0)
    server_fps_average = models.FloatField(default=0)
    frame_time = models.FloatField(default=0)
    world_days = models.PositiveIntegerField(default=0)
    base_camps = models.PositiveIntegerField(default=0)
    uptime = models.PositiveBigIntegerField(default=0)

    class Meta:
        ordering = ["source_clock"]


class Player(models.Model):
    public_id = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)
    account_name = models.CharField(max_length=128, blank=True)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField(db_index=True)
    level = models.PositiveIntegerField(default=0)
    building_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["name"]


class PlayerSession(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="sessions")
    started_at = models.DateTimeField(db_index=True)
    last_seen = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["player"],
                condition=models.Q(ended_at__isnull=True),
                name="one_active_session_per_player",
            )
        ]


class PositionSample(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="positions")
    source_clock = models.DateTimeField(db_index=True)
    x = models.FloatField()
    y = models.FloatField()
    ping = models.FloatField(default=0)
    level = models.PositiveIntegerField(default=0)
    building_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["source_clock"]
        constraints = [
            models.UniqueConstraint(
                fields=["player", "source_clock"], name="unique_player_position_sample"
            )
        ]


class ServerEvent(models.Model):
    JOIN = "join"
    LEAVE = "leave"
    EVENT_TYPES = [(JOIN, "Join"), (LEAVE, "Leave")]

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=8, choices=EVENT_TYPES)
    source_clock = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-source_clock"]


class RuntimeState(models.Model):
    key = models.CharField(max_length=64, unique=True)
    value = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="site_profile"
    )
    email_verified = models.BooleanField(default=False)
    approved = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)
    admin_notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_site_profiles",
    )

    class Meta:
        ordering = ["-created_at"]


class AuthThrottle(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    window_started_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveIntegerField(default=0)
