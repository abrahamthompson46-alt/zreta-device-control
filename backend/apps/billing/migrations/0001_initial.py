import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Feature",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("key", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=150)),
                ("description", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["key"]},
        ),
        migrations.CreateModel(
            name="Plan",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.SlugField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=150)),
                ("description", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
                ("is_default", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="plan",
            constraint=models.UniqueConstraint(
                condition=models.Q(is_default=True),
                fields=("is_default",),
                name="uniq_one_default_plan",
            ),
        ),
        migrations.CreateModel(
            name="PlanPrice",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("currency", models.CharField(default="GHS", max_length=3)),
                ("amount_minor", models.PositiveIntegerField(default=0)),
                ("interval", models.CharField(choices=[("month", "Month"), ("year", "Year"), ("none", "None")], default="month", max_length=16)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="prices", to="billing.plan")),
            ],
            options={"ordering": ["currency", "interval"]},
        ),
        migrations.AddConstraint(
            model_name="planprice",
            constraint=models.UniqueConstraint(fields=("plan", "currency", "interval"), name="uniq_plan_price_currency_interval"),
        ),
        migrations.CreateModel(
            name="PlanEntitlement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("enabled", models.BooleanField(default=True)),
                ("limit", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("feature", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="plan_entitlements", to="billing.feature")),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entitlements", to="billing.plan")),
            ],
            options={"ordering": ["feature__key"]},
        ),
        migrations.AddConstraint(
            model_name="planentitlement",
            constraint=models.UniqueConstraint(fields=("plan", "feature"), name="uniq_plan_feature"),
        ),
        migrations.CreateModel(
            name="Subscription",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("trialing", "Trialing"), ("active", "Active"), ("past_due", "Past due"), ("canceled", "Canceled"), ("expired", "Expired")], db_index=True, default="active", max_length=20)),
                ("trial_ends_at", models.DateTimeField(blank=True, null=True)),
                ("current_period_end", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="subscription", to="accounts.organization")),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="subscriptions", to="billing.plan")),
            ],
            options={"ordering": ["organization__name"]},
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(max_length=32)),
                ("provider_reference", models.CharField(max_length=128)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("succeeded", "Succeeded"), ("failed", "Failed"), ("canceled", "Canceled")], default="pending", max_length=20)),
                ("currency", models.CharField(default="GHS", max_length=3)),
                ("amount_minor", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payments", to="accounts.organization")),
                ("subscription", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payments", to="billing.subscription")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.UniqueConstraint(fields=("provider", "provider_reference"), name="uniq_payment_provider_reference"),
        ),
        migrations.CreateModel(
            name="EntitlementOverride",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("effect", models.CharField(choices=[("grant", "Grant"), ("deny", "Deny")], max_length=8)),
                ("limit", models.PositiveIntegerField(blank=True, null=True)),
                ("reason", models.CharField(blank=True, default="", max_length=200)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="entitlement_overrides", to=settings.AUTH_USER_MODEL)),
                ("feature", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="overrides", to="billing.feature")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entitlement_overrides", to="accounts.organization")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
