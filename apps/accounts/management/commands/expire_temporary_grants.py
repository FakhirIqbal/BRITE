"""Scheduled job: remove expired temporary grants and write audit entries (actor type: scheduled)."""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.services import expire_temporary_grants
from apps.core.context import system_actor


class Command(BaseCommand):
    help = "Remove expired temporary access grants (run nightly)."

    def handle(self, *args, **options):
        with transaction.atomic(), system_actor("Scheduled job", scheduled=True):
            count = expire_temporary_grants()
        if options.get("verbosity", 1):
            self.stdout.write(self.style.SUCCESS(f"Expired and removed {count} temporary grant(s)."))
