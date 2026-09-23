from django.core.management.base import BaseCommand

from apps.policies.schedules import process_due_schedules


class Command(BaseCommand):
    help = "Publish due PolicySchedule rows (activate_at <= now). FCM wake follows publish."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Max schedules to process in one run (default 50).",
        )

    def handle(self, *args, **options):
        result = process_due_schedules(limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(
                f"due={result['due']} completed={result['completed']} failed={result['failed']}"
            )
        )
