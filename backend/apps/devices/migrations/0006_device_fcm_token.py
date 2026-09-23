from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("devices", "0005_device_status_dns_filter"),
    ]

    operations = [
        migrations.AddField(
            model_name="device",
            name="fcm_registration_token",
            field=models.CharField(blank=True, max_length=512, null=True),
        ),
        migrations.AddField(
            model_name="device",
            name="fcm_token_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
