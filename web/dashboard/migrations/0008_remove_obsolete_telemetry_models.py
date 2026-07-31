from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0007_userprofile_terms")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name="ConnectorBatch"),
                migrations.DeleteModel(name="VmMetricSample"),
            ],
        ),
    ]
