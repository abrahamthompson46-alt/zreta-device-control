import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("devices", "0006_device_fcm_token"),
    ]

    operations = [
        migrations.CreateModel(
            name="InstalledApplication",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("package_name", models.CharField(max_length=255)),
                ("label", models.CharField(max_length=150)),
                ("version_name", models.CharField(blank=True, default="", max_length=64)),
                ("version_code", models.BigIntegerField()),
                ("first_seen", models.DateTimeField()),
                ("last_reported", models.DateTimeField()),
                ("removed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "device",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="installed_applications",
                        to="devices.device",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="installed_applications",
                        to="accounts.organization",
                    ),
                ),
            ],
            options={
                "ordering": ["package_name"],
            },
        ),
        migrations.AddConstraint(
            model_name="installedapplication",
            constraint=models.UniqueConstraint(
                fields=("device", "package_name"),
                name="uniq_device_installed_package",
            ),
        ),
        migrations.AddIndex(
            model_name="installedapplication",
            index=models.Index(fields=["organization", "device"], name="inst_app_org_device_idx"),
        ),
    ]
