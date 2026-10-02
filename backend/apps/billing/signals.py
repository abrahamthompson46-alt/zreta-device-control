from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import Organization
from apps.billing.models import Plan, Subscription, SubscriptionStatus


@receiver(post_save, sender=Organization)
def ensure_default_subscription(sender, instance: Organization, created: bool, **kwargs):
    if not created:
        return
    if Subscription.objects.filter(organization=instance).exists():
        return
    plan = Plan.objects.filter(is_default=True, is_active=True).first()
    if plan is None:
        return
    Subscription.objects.create(organization=instance, plan=plan, status=SubscriptionStatus.ACTIVE)
