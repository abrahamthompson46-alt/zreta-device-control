from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("devices", "0004_device_status_policy_ack_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="devicestatus",
            name="dns_filter_state",
            field=models.CharField(
                choices=[
                    ("unknown", "Unknown"),
                    ("stopped", "Stopped"),
                    ("running", "Running"),
                    ("consent_required", "VPN consent required"),
                    ("failed", "Failed"),
                ],
                default="unknown",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="devicestatus",
            name="dns_filter_error",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
