from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0010_player_longest_session_minutes_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="player",
            name="ip_address",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="player",
            name="ip_observed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
