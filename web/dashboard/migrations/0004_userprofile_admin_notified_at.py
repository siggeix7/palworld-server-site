from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0003_userprofile_must_change_password")]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="admin_notified_at",
            field=models.DateTimeField(blank=True, null=True),
        )
    ]
