from datetime import timedelta

from django.utils import timezone


def presence_from_last_seen(last_seen_at, *, now=None, window=None) -> str:
    """Derived presence. Does not change the connectivity value last reported by the device."""
    if last_seen_at is None:
        return "offline"
    current = now or timezone.now()
    grace = window or timedelta(minutes=20)
    if current - last_seen_at <= grace:
        return "online"
    return "offline"
