from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0002_seed_default_plan"),
    ]

    operations = [
        migrations.AlterField(
            model_name="feature",
            name="key",
            field=models.CharField(max_length=64, unique=True),
        ),
    ]
