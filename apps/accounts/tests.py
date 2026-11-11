"""Milestone 2 acceptance: roles see only their sections; restricted areas are unreachable by any route."""
from __future__ import annotations

from django.db import connection, transaction

from apps.accounts.models import IndividualException, SystemOwner
from apps.accounts.roles import Capability
from apps.core.context import ActorContext
from apps.core.db import apply_db_context
from apps.core.tests.base import FoundationTestCase


class RoleSectionsTests(FoundationTestCase):
    def test_each_role_sees_only_its_own_sections(self):
        expectations = {
            "coordinator": (self.coordinator, {"Work"}, {"Administration"}),
            "billing": (self.billing, {"Work"}, {"Administration", "People (restricted)"}),
            "hr": (self.hr, {"Staffing"}, {"Administration", "Work"}),
            "operations": (self.operations, {"Oversight"}, {"Administration"}),
            "admin": (self.admin, {"Administration"}, {"Work", "Oversight", "Staffing"}),
        }
        for name, (user, expected, forbidden) in expectations.items():
            with self.subTest(role=name):
                response = self.client_for(user).get("/api/auth/me/")
                self.assertEqual(response.status_code, 200)
                labels = {g["label"] for g in response.data["navigation"]}
                self.assertTrue(expected <= labels, f"{name}: {labels}")
                self.assertFalse(forbidden & labels, f"{name} unexpectedly sees {forbidden & labels}")

    def test_multi_role_user_sees_all_held_roles_sections(self):
        response = self.client_for(self.exec_admin).get("/api/auth/me/")
        roles = {r["code"] for r in response.data["roles"]}
        self.assertEqual(roles, {"ceo_executive_admin", "clinical_director", "administrator", "staff_self_service"})
        labels = {g["label"] for g in response.data["navigation"]}
        self.assertIn("Administration", labels)
        self.assertIn("CEO / Executive Admin", labels)
        # A section shared by several of the user's roles (Home, Clients) is listed once.
        keys = [i["key"] for g in response.data["navigation"] for i in g["items"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(response.data["is_system_owner"])

    def test_unauthenticated_requests_are_refused(self):
        for path in ["/api/auth/me/", "/api/clients/", "/api/admin/users/", "/api/audit/events/"]:
            self.assertIn(self.client.get(path).status_code, (401, 403), path)


class RestrictedAccessTests(FoundationTestCase):
    """An ordinary role cannot reach restricted employment data, quiz configuration or the database by any route."""

    def test_ordinary_role_cannot_reach_admin_routes(self):
        billing = self.client_for(self.billing)
        for path in ["/api/admin/users/", "/api/admin/workspace-groups/", "/api/admin/system-owners/", "/api/admin/configuration/status-sets/", "/api/audit/events/", "/api/admin/shared-drive/"]:
            with self.subTest(path=path):
                self.assertEqual(billing.get(path).status_code, 403)
        self.assertEqual(billing.post("/api/admin/configuration/status-sets/workstream_status/options/", {"code": "x", "label": "X"}).status_code, 403)

    def test_capabilities_reported_match_role_defaults(self):
        caps = self.client_for(self.billing).get("/api/auth/me/").data["capabilities"]
        self.assertEqual(caps[Capability.EMPLOYMENT_SCREENING_DETAIL], "none")
        self.assertEqual(caps[Capability.QUIZ_CONFIGURATION], "none")
        self.assertEqual(caps[Capability.CLIENT_OPERATIONAL_DATA], "edit")
        caps = self.client_for(self.staff).get("/api/auth/me/").data["capabilities"]
        self.assertTrue(all(level == "none" for level in caps.values()))

    def test_database_denies_rows_without_capability(self):
        """Row-level security: a session carrying Billing's capabilities reads zero audit rows and no exceptions of others."""
        from apps.audit.models import AuditEvent
        from apps.clients.models import Client

        with self.as_system():
            from apps.clients.services import create_client
            create_client(first_name="Noah", last_name="Testchild", age_years=4)
        self.assertGreater(AuditEvent.objects.count(), 0)  # autocommit outside a transaction: owner sees rows? No: RLS forces deny.
        with transaction.atomic():
            # No context at all → fail closed on every protected table.
            apply_db_context(ActorContext())
            self.assertEqual(Client.objects.count(), 0)
            self.assertEqual(AuditEvent.objects.count(), 0)
            # Billing context → client data yes, admin audit timeline no (only client-linked events).
            apply_db_context(ActorContext(user_id=self.billing.pk, actor_type="human", capabilities={Capability.CLIENT_OPERATIONAL_DATA: "edit"}))
            self.assertEqual(Client.objects.count(), 1)
            self.assertEqual(AuditEvent.objects.filter(client_id__isnull=True).count(), 0)
            # Staff self-service (no capabilities) → nothing.
            apply_db_context(ActorContext(user_id=self.staff.pk, actor_type="human", capabilities={}))
            self.assertEqual(Client.objects.count(), 0)
            self.assertEqual(IndividualException.objects.exclude(user=self.staff).count(), 0)
            with connection.cursor() as cur:
                cur.execute("SELECT count(*) FROM clients_client")
                self.assertEqual(cur.fetchone()[0], 0)

    def test_admin_without_client_capability_cannot_read_clients(self):
        with self.as_system():
            from apps.clients.services import create_client
            create_client(first_name="Noah", last_name="Testchild", age_years=4)
        response = self.client_for(self.admin).get("/api/clients/")
        self.assertEqual(response.status_code, 403)


class ExceptionsAndOwnersTests(FoundationTestCase):
    def test_exception_grants_access_and_is_audited(self):
        admin = self.client_for(self.admin)
        response = admin.post(
            f"/api/admin/users/{self.billing.pk}/exceptions/",
            {"capability": Capability.AUDIT_HISTORY, "kind": "grant", "level": "view", "reason": "Covering review during leave", "duration": "temporary", "expires_on": "2099-01-01"},
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.client_for(self.billing).get("/api/audit/events/").status_code, 200)
        me = self.client_for(self.billing).get("/api/auth/me/").data
        self.assertEqual(me["capabilities"][Capability.AUDIT_HISTORY], "view")
        self.assertIn("Through an exception", {g["label"] for g in me["navigation"]})
        timeline = admin.get("/api/audit/events/?event_type=access_change").data["results"]
        self.assertTrue(any("Exception granted" in e["summary"] and e["actor_type"] == "human" for e in timeline))

    def test_removal_overrides_role_default(self):
        admin = self.client_for(self.admin)
        admin.post(f"/api/admin/users/{self.billing.pk}/exceptions/", {"capability": Capability.CLIENT_OPERATIONAL_DATA, "kind": "remove", "reason": "Investigation"})
        self.assertEqual(self.client_for(self.billing).get("/api/clients/").status_code, 403)

    def test_self_granted_exception_is_flagged_and_notifies_other_owner(self):
        from django.core import mail

        admin = self.client_for(self.admin)
        response = admin.post(
            f"/api/admin/users/{self.admin.pk}/exceptions/",
            {"capability": Capability.CREDENTIALING, "kind": "grant", "level": "view", "reason": "Reviewing data mapping", "duration": "permanent"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["is_self_granted"])
        self.assertEqual(response.data["notified_owner_emails"], [self.exec_admin.email])
        self.assertEqual(len(mail.outbox), 1)
        events = admin.get("/api/audit/events/?self_granted=1").data["results"]
        self.assertTrue(events and "self_granted" in events[0]["flags"])

    def test_temporary_grant_expiry_job_is_scheduled_actor(self):
        import datetime as dt

        from django.core.management import call_command

        with self.as_system():
            exc = IndividualException.objects.create(
                user=self.billing, capability=Capability.EXPORTS, kind="grant", level="view", reason="Quarterly export",
                duration="temporary", expires_on=dt.date(2000, 1, 1), granted_by_label="Chris Walker",
            )
        call_command("expire_temporary_grants", verbosity=0)
        exc.refresh_from_db()
        self.assertIsNotNone(exc.removed_at)
        events = self.client_for(self.admin).get("/api/audit/events/?actor_type=scheduled").data["results"]
        self.assertTrue(any("expired and removed" in e["summary"] for e in events))

    def test_last_two_system_owners_cannot_be_removed(self):
        admin = self.client_for(self.admin)
        owners = admin.get("/api/admin/system-owners/").data
        self.assertEqual(len(owners["results"]), 2)
        target = owners["results"][0]["id"]
        response = admin.post(f"/api/admin/system-owners/{target}/remove/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("at least 2 System Owners", response.data["detail"])
        self.assertEqual(SystemOwner.objects.filter(removed_at__isnull=True).count(), 2)
        # Add a third, then removal succeeds.
        response = admin.post("/api/admin/system-owners/", {"user_id": self.operations.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(admin.post(f"/api/admin/system-owners/{target}/remove/").status_code, 200)

    def test_non_owner_administrator_cannot_change_access(self):
        with self.as_system():
            SystemOwner.objects.filter(user=self.admin).update(removed_at="2026-01-01T00:00:00Z")
        admin = self.client_for(self.admin)
        response = admin.post(f"/api/admin/users/{self.billing.pk}/exceptions/", {"capability": Capability.EXPORTS, "kind": "grant", "level": "view", "reason": "x"})
        self.assertEqual(response.status_code, 403)
