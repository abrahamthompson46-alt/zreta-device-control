# Generated manually for Phase 3 location (additive).

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("devices", "0002_deviceassertionjti"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="location_authorized_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="device",
            name="location_collection_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="LocationRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("client_event_id", models.UUIDField()),
                ("captured_at", models.DateTimeField()),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("latitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("longitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("accuracy_m", models.FloatField(blank=True, null=True)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("fused", "Fused"),
                            ("gps", "GPS"),
                            ("network", "Network"),
                            ("unknown", "Unknown"),
                        ],
                        default="unknown",
                        max_length=16,
                    ),
                ),
                ("is_mock", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "device",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="location_records",
                        to="devices.device",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="location_records",
                        to="accounts.organization",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="devicestatus",
            name="last_location",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="devices.locationrecord",
            ),
        ),
        migrations.AddField(
            model_name="devicestatus",
            name="location_last_error",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddIndex(
            model_name="locationrecord",
            index=models.Index(fields=["organization", "-captured_at"], name="loc_org_captured_idx"),
        ),
        migrations.AddIndex(
            model_name="locationrecord",
            index=models.Index(fields=["device", "-captured_at"], name="loc_device_captured_idx"),
        ),
        migrations.AddConstraint(
            model_name="locationrecord",
            constraint=models.UniqueConstraint(
                fields=("device", "client_event_id"),
                name="uniq_device_location_client_event",
            ),
        ),
        migrations.AddConstraint(
            model_name="locationrecord",
            constraint=models.CheckConstraint(
                condition=models.Q(("latitude__gte", -90), ("latitude__lte", 90)),
                name="location_lat_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="locationrecord",
            constraint=models.CheckConstraint(
                condition=models.Q(("longitude__gte", -180), ("longitude__lte", 180)),
                name="location_lon_range",
            ),
        ),
    ]
