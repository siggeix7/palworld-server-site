from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_missing_profiles(apps, schema_editor):
    user_model = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    user_profile = apps.get_model("dashboard", "UserProfile")
    user_profile.objects.bulk_create(
        user_profile(user_id=user_id)
        for user_id in user_model.objects.values_list("pk", flat=True)
    )


def validate_existing_identities(apps, schema_editor):
    user_model = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    seen_usernames = set()
    seen_emails = set()
    for username, email in user_model.objects.values_list("username", "email"):
        if not username.isascii() or (email and not email.isascii()):
            raise RuntimeError(
                "Authentication migration requires ASCII usernames and email addresses"
            )
        normalized_username = username.casefold()
        normalized_email = email.casefold()
        if normalized_username in seen_usernames:
            raise RuntimeError(
                "Authentication migration found case-insensitive duplicate usernames"
            )
        if normalized_email and normalized_email in seen_emails:
            raise RuntimeError(
                "Authentication migration found case-insensitive duplicate emails"
            )
        seen_usernames.add(normalized_username)
        if normalized_email:
            seen_emails.add(normalized_email)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dashboard", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuthThrottle",
            fields=[
                ("key", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("window_started_at", models.DateTimeField(db_index=True)),
                ("attempts", models.PositiveIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name="UserProfile",
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
                ("email_verified", models.BooleanField(default=False)),
                ("approved", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approved_site_profiles",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="site_profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.RunPython(create_missing_profiles, migrations.RunPython.noop),
        migrations.RunPython(validate_existing_identities, migrations.RunPython.noop),
        migrations.RunSQL(
            sql=[
                "CREATE UNIQUE INDEX auth_user_username_ci_uniq "
                "ON auth_user (LOWER(username))",
                "CREATE UNIQUE INDEX auth_user_email_ci_uniq "
                "ON auth_user (LOWER(email)) WHERE email <> ''",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS auth_user_email_ci_uniq",
                "DROP INDEX IF EXISTS auth_user_username_ci_uniq",
            ],
        ),
    ]
