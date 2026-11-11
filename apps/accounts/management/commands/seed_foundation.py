"""
Seed the Milestone 2 foundation: role capability defaults, Workspace
group → role mappings, status sets and the two System Owners named in
BRITE_SYSTEM_OWNER_EMAILS. With --dev-users it also creates fictional
test accounts (one per role) for the development sign-in. Idempotent.
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import RoleCapabilityDefault, SystemOwner, User, WorkspaceGroupMapping, WorkspaceGroupMembership
from apps.accounts.roles import DEFAULT_GROUP_MAPPINGS, DEFAULT_ROLE_CAPABILITIES, Capability, Role
from apps.audit.services import record_event
from apps.configuration.models import SEEDED_STATUS_SETS, StatusOption, StatusSet
from apps.core.context import system_actor

# Fictional development accounts. Not real people.
DEV_USERS = [
    ("maya.torres", "Maya Torres", [Role.CLIENT_COORDINATOR, Role.STAFF_SELF_SERVICE]),
    ("daniel.reyes", "Daniel Reyes", [Role.BILLING, Role.STAFF_SELF_SERVICE]),
    ("priya.nair", "Priya Nair", [Role.HR_STAFFING, Role.STAFF_SELF_SERVICE]),
    ("alicia.grant", "Dr. Alicia Grant", [Role.CLINICAL, Role.STAFF_SELF_SERVICE]),
    ("renee.coleman", "Dr. Renee Coleman", [Role.CLINICAL_DIRECTOR, Role.STAFF_SELF_SERVICE]),
    ("sam.ortiz", "Sam Ortiz", [Role.OPERATIONS, Role.STAFF_SELF_SERVICE]),
    ("chris.walker", "Chris Walker", [Role.ADMINISTRATOR, Role.STAFF_SELF_SERVICE]),
    ("ingrid.akinduro", "Ingrid Akinduro", [Role.CEO_EXECUTIVE_ADMIN, Role.CLINICAL_DIRECTOR, Role.ADMINISTRATOR, Role.STAFF_SELF_SERVICE]),
    ("lena.park", "Lena Park", [Role.CREDENTIALING, Role.HR_STAFFING, Role.STAFF_SELF_SERVICE]),
    ("jordan.blake", "Jordan Blake", [Role.STAFF_SELF_SERVICE]),
]


class Command(BaseCommand):
    help = "Seed role defaults, group mappings, status sets and System Owners."

    def add_arguments(self, parser):
        parser.add_argument("--dev-users", action="store_true", help="Also create fictional development accounts.")
        parser.add_argument("--domain", default=None, help="Workspace domain for seeded group emails (default: GOOGLE_WORKSPACE_DOMAIN or example.test).")

    def handle(self, *args, **options):
        if options.get("verbosity", 1) == 0:
            self.stdout = open(__import__("os").devnull, "w")
        domain = options["domain"] or settings.GOOGLE_WORKSPACE_DOMAIN or "example.test"
        with transaction.atomic(), system_actor("Seed"):
            self.seed_defaults()
            mappings = self.seed_groups(domain)
            self.seed_status_sets()
            if options["dev_users"]:
                self.seed_dev_users(domain, mappings)
            self.seed_system_owners(domain)
        self.stdout.write(self.style.SUCCESS("Foundation seed complete."))

    def seed_defaults(self):
        created = 0
        for role, caps in DEFAULT_ROLE_CAPABILITIES.items():
            for cap in Capability.ORDER:
                _, was_created = RoleCapabilityDefault.objects.get_or_create(
                    role=role, capability=cap, defaults={"level": caps.get(cap, "none"), "updated_by_label": "Seed"}
                )
                created += was_created
        self.stdout.write(f"Role capability defaults: {created} created")

    def seed_groups(self, domain: str) -> dict[str, WorkspaceGroupMapping]:
        mappings = {}
        created = 0
        for local_part, role in DEFAULT_GROUP_MAPPINGS:
            mapping, was_created = WorkspaceGroupMapping.objects.get_or_create(
                group_email=f"{local_part}@{domain}", defaults={"role": role, "updated_by_label": "Seed"}
            )
            mappings[role] = mapping
            created += was_created
        self.stdout.write(f"Workspace group mappings: {created} created")
        return mappings

    def seed_status_sets(self):
        for order, spec in enumerate(SEEDED_STATUS_SETS):
            status_set, _ = StatusSet.objects.get_or_create(
                key=spec["key"],
                defaults={"name": spec["name"], "description": spec["description"], "reference": spec["reference"], "sort_order": order, "updated_by_label": "Seed"},
            )
            for idx, (code, label, tone) in enumerate(spec["options"], start=1):
                StatusOption.objects.get_or_create(
                    status_set=status_set, code=code, defaults={"label": label, "tone": tone, "sort_order": idx, "updated_by_label": "Seed"}
                )
        self.stdout.write(f"Status sets: {StatusSet.objects.count()} present")

    def seed_dev_users(self, domain: str, mappings: dict[str, WorkspaceGroupMapping]):
        for local_part, name, roles in DEV_USERS:
            email = f"{local_part}@{domain}"
            user, created = User.objects.get_or_create(email=email, defaults={"full_name": name})
            if created:
                user.set_unusable_password()
                user.save()
            for role in roles:
                mapping = mappings.get(role) or WorkspaceGroupMapping.objects.filter(role=role, is_active=True).first()
                if mapping and not WorkspaceGroupMembership.objects.filter(user=user, group=mapping, removed_at__isnull=True).exists():
                    WorkspaceGroupMembership.objects.create(user=user, group=mapping, source=WorkspaceGroupMembership.SOURCE_MANUAL)
        self.stdout.write(f"Development users: {len(DEV_USERS)} ensured (fictional)")

    def seed_system_owners(self, domain: str):
        emails = [e.lower() for e in settings.BRITE_SYSTEM_OWNER_EMAILS]
        if not emails and settings.DEV_AUTH_ENABLED:
            emails = [f"chris.walker@{domain}", f"ingrid.akinduro@{domain}"]
        if not emails:
            self.stdout.write(self.style.WARNING("BRITE_SYSTEM_OWNER_EMAILS not set: no System Owners seeded."))
            return
        admin_group = WorkspaceGroupMapping.objects.filter(role=Role.ADMINISTRATOR, is_active=True).first()
        for email in emails:
            user, _ = User.objects.get_or_create(email=email, defaults={"full_name": email.split("@")[0].replace(".", " ").title()})
            if admin_group and not WorkspaceGroupMembership.objects.filter(user=user, group=admin_group, removed_at__isnull=True).exists():
                WorkspaceGroupMembership.objects.create(user=user, group=admin_group, source=WorkspaceGroupMembership.SOURCE_MANUAL)
            if not SystemOwner.objects.filter(user=user, removed_at__isnull=True).exists():
                owner = SystemOwner.objects.create(user=user, assigned_by_label="Sprint 0")
                record_event(owner, event_type="access_change", action="system_owner_added", summary=f"{user} assigned as System Owner (Sprint 0)", subject_user_id=user.pk)
        self.stdout.write(f"System Owners: {SystemOwner.objects.filter(removed_at__isnull=True).count()} active")
