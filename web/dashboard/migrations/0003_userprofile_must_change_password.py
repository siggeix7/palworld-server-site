from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0002_userprofile")]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="must_change_password",
            field=models.BooleanField(default=False),
        )
    ]
