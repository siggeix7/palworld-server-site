from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0006_guildsnapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="terms_accepted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="terms_version",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]