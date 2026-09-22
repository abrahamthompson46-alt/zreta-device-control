from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Device, DeviceStatus


@receiver(post_save, sender=Device)
def create_device_status(sender, instance, created, **kwargs):
    if created:
        DeviceStatus.objects.get_or_create(device=instance)
