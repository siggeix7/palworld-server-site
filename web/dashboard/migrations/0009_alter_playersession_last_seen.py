from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0008_remove_obsolete_telemetry_models'),
    ]

    operations = [
        migrations.AlterField(
            model_name='playersession',
            name='last_seen',
            field=models.DateTimeField(db_index=True),
        ),
    ]
