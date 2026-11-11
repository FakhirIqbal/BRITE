"""Shared fixtures: seeded foundation + fictional users per role."""
from __future__ import annotations

from django.core.management import call_command
from django.db import transaction
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.core.context import system_actor


class FoundationTestCase(APITestCase):
    DOMAIN = "example.test"

    @classmethod
    def setUpTestData(cls):
        call_command("seed_foundation", "--dev-users", "--domain", cls.DOMAIN, verbosity=0)
        cls.coordinator = User.objects.get(email=f"maya.torres@{cls.DOMAIN}")
        cls.billing = User.objects.get(email=f"daniel.reyes@{cls.DOMAIN}")
        cls.hr = User.objects.get(email=f"priya.nair@{cls.DOMAIN}")
        cls.operations = User.objects.get(email=f"sam.ortiz@{cls.DOMAIN}")
        cls.admin = User.objects.get(email=f"chris.walker@{cls.DOMAIN}")
        cls.exec_admin = User.objects.get(email=f"ingrid.akinduro@{cls.DOMAIN}")
        cls.staff = User.objects.get(email=f"jordan.blake@{cls.DOMAIN}")

    def client_for(self, user: User) -> APIClient:
        client = APIClient()
        # Signing in updates last_login on the user row; in production the sign-in
        # view runs this as the system, so mirror that here.
        with transaction.atomic(), system_actor("Test sign-in"):
            client.force_login(user)
        return client

    def as_system(self):
        """Context manager: run setup writes as the system inside a transaction."""
        class _Scope:
            def __enter__(_self):
                _self.tx = transaction.atomic()
                _self.tx.__enter__()
                _self.sys = system_actor("Test setup")
                _self.sys.__enter__()
                return _self

            def __exit__(_self, *exc):
                _self.sys.__exit__(*exc)
                return _self.tx.__exit__(*exc)

        return _Scope()
