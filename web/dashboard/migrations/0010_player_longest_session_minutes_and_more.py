from django.db import migrations, models


def backfill_player_rollups(apps, schema_editor):
    Player = apps.get_model("dashboard", "Player")
    PlayerSession = apps.get_model("dashboard", "PlayerSession")
    for player in Player.objects.all():
        sessions = list(
            PlayerSession.objects.filter(player=player).values_list(
                "started_at", "ended_at", "last_seen"
            )
        )
        closed_seconds = 0
        longest = 0
        for started_at, ended_at, last_seen in sessions:
            end = ended_at if ended_at is not None else last_seen
            duration = max(0, int((end - started_at).total_seconds()))
            if ended_at is not None:
                closed_seconds += duration
                longest = max(longest, duration)
        player.minutes_lifetime = closed_seconds // 60
        player.session_count_lifetime = len(sessions)
        player.longest_session_minutes = longest // 60
        player.save(update_fields=[
            "minutes_lifetime",
            "session_count_lifetime",
            "longest_session_minutes",
        ])


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0009_alter_playersession_last_seen'),
    ]

    operations = [
        migrations.AddField(
            model_name='player',
            name='longest_session_minutes',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='player',
            name='minutes_lifetime',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='player',
            name='session_count_lifetime',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(backfill_player_rollups, migrations.RunPython.noop),
    ]