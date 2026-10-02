from django.db import migrations

from apps.billing.catalog import DEFAULT_PLAN_CODE, DEFAULT_PLAN_NAME, FEATURE_CATALOG


def seed_default_plan(apps, schema_editor):
    Feature = apps.get_model("billing", "Feature")
    Plan = apps.get_model("billing", "Plan")
    PlanPrice = apps.get_model("billing", "PlanPrice")
    PlanEntitlement = apps.get_model("billing", "PlanEntitlement")
    Subscription = apps.get_model("billing", "Subscription")
    Organization = apps.get_model("accounts", "Organization")

    features = {}
    for key, name, description in FEATURE_CATALOG:
        feature, _created = Feature.objects.get_or_create(
            key=key,
            defaults={"name": name, "description": description, "is_active": True},
        )
        features[key] = feature

    plan, _created = Plan.objects.get_or_create(
        code=DEFAULT_PLAN_CODE,
        defaults={"name": DEFAULT_PLAN_NAME, "is_default": True, "is_active": True, "description": "Includes every feature that already works."},
    )
    if not plan.is_default:
        plan.is_default = True
        plan.is_active = True
        plan.save(update_fields=["is_default", "is_active"])

    PlanPrice.objects.get_or_create(
        plan=plan,
        currency="GHS",
        interval="none",
        defaults={"amount_minor": 0, "is_active": True},
    )
    for feature in features.values():
        PlanEntitlement.objects.get_or_create(
            plan=plan,
            feature=feature,
            defaults={"enabled": True, "limit": None},
        )
    for organization in Organization.objects.all():
        Subscription.objects.get_or_create(
            organization=organization,
            defaults={"plan": plan, "status": "active"},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0001_initial"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_default_plan, migrations.RunPython.noop),
    ]
