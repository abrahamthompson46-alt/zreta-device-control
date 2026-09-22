from django.core.management.base import BaseCommand

from apps.devices.location import purge_expired_locations


class Command(BaseCommand):
    help = "Delete LocationRecord rows older than LOCATION_RETENTION_DAYS."

    def handle(self, *args, **options):
        deleted = purge_expired_locations()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} expired location record(s)."))
