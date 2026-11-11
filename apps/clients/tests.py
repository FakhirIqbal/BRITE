"""Milestone 2 acceptance: schema rules, concurrent-write refusal, audit history."""
from __future__ import annotations

from django.db import IntegrityError, connection, transaction

from apps.audit.models import AuditEvent
from apps.clients.models import ServiceEpisode, Workstream
from apps.core.tests.base import FoundationTestCase


class ClientSchemaTests(FoundationTestCase):
    def create_client(self, api=None, **overrides):
        api = api or self.client_for(self.coordinator)
        payload = {"first_name": "Noah", "last_name": "Bennett", "age_years": 4, "settings_requested": ["home", "school"]}
        payload.update(overrides)
        response = api.post("/api/clients/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def test_creation_assigns_permanent_id_code_name_and_six_workstreams(self):
        data = self.create_client()
        self.assertRegex(data["client_id"], r"^BC-\d{6}$")
        self.assertTrue(data["code_name"])
        self.assertEqual(len(data["episodes"]), 1)
        episode = data["episodes"][0]
        self.assertEqual(episode["number"], 1)
        self.assertEqual({w["kind"] for w in episode["workstreams"]}, set(Workstream.KIND_ORDER))
        for w in episode["workstreams"]:
            for field in ("status", "owner", "next_action", "due_date", "blocker", "waiting_on", "updated_at"):
                self.assertIn(field, w)
        owned = [w for w in episode["workstreams"] if w["owner"]]
        self.assertEqual(len(owned), 1)
        self.assertEqual(owned[0]["kind"], "client_coordination")
        self.assertEqual(episode["journey_phase"], "potential_client")
        self.assertNotIn("overall_status", data)

    def test_client_ids_are_never_reused(self):
        first = self.create_client()["client_id"]
        second = self.create_client(first_name="Mia", last_name="Lopez")["client_id"]
        self.assertLess(first, second)

    def test_duplicate_warning_never_merges(self):
        self.create_client()
        api = self.client_for(self.coordinator)
        response = api.post("/api/clients/", {"first_name": "Noah", "last_name": "Bennett", "age_years": 5}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "possible_duplicates")
        response = api.post("/api/clients/", {"first_name": "Noah", "last_name": "Bennett", "age_years": 5, "acknowledge_duplicates": True}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(api.get("/api/clients/?q=Bennett").data["count"], 2)

    def test_one_active_episode_per_client_enforced_at_database(self):
        data = self.create_client()
        with self.as_system():
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    ServiceEpisode.objects.create(client_id=data["id"], number=2)

    def test_closed_episode_is_read_only(self):
        api = self.client_for(self.coordinator)
        data = self.create_client(api)
        episode = data["episodes"][0]
        ws = episode["workstreams"][0]
        response = api.post(f"/api/clients/episodes/{episode['id']}/close/", {"closure_reason": "unable_to_reach", "closure_note": "No reply", "version": episode["version"]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["state"], "closed")
        # API refuses edits.
        response = api.patch(f"/api/clients/workstreams/{ws['id']}/", {"next_action": "Call", "version": ws["version"]}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "read_only")
        # Database refuses edits even if the API were bypassed.
        with self.as_system():
            with self.assertRaises(Exception):
                with transaction.atomic():
                    Workstream.objects.filter(pk=ws["id"]).update(next_action="direct write")
            with self.assertRaises(Exception):
                with transaction.atomic():
                    ServiceEpisode.objects.filter(pk=episode["id"]).update(closure_note="tamper")
        # Reactivation opens Episode 2; Episode 1 stays closed.
        response = api.post(f"/api/clients/{data['id']}/reactivate/")
        self.assertEqual(response.status_code, 201)
        numbers = [(e["number"], e["state"]) for e in response.data["episodes"]]
        self.assertEqual(numbers, [(1, "closed"), (2, "open")])
        self.assertEqual(response.data["client_id"], data["client_id"])

    def test_closure_requires_structured_reason(self):
        api = self.client_for(self.coordinator)
        episode = self.create_client(api)["episodes"][0]
        response = api.post(f"/api/clients/episodes/{episode['id']}/close/", {"closure_reason": "", "version": episode["version"]}, format="json")
        self.assertEqual(response.status_code, 400)


class ConcurrencyTests(FoundationTestCase):
    def test_second_concurrent_save_is_refused_naming_who_and_when(self):
        maya = self.client_for(self.coordinator)
        daniel = self.client_for(self.billing)
        data = maya.post("/api/clients/", {"first_name": "Ivy", "last_name": "Chen", "age_years": 3}, format="json").data
        ws = next(w for w in data["episodes"][0]["workstreams"] if w["kind"] == "billing")
        first = daniel.patch(f"/api/clients/workstreams/{ws['id']}/", {"next_action": "Verify benefits", "status": "in_progress", "version": ws["version"]}, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["version"], ws["version"] + 1)
        second = maya.patch(f"/api/clients/workstreams/{ws['id']}/", {"next_action": "Something else", "version": ws["version"]}, format="json")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.data["code"], "concurrent_write")
        self.assertEqual(second.data["changed_by"], "Daniel Reyes")
        self.assertIsNotNone(second.data["changed_at"])
        self.assertEqual(second.data["current_version"], ws["version"] + 1)
        self.assertIn("Daniel Reyes", second.data["detail"])
        # The first save stands; nothing was silently overwritten.
        refreshed = maya.get(f"/api/clients/{data['id']}/").data
        self.assertEqual(next(w for w in refreshed["episodes"][0]["workstreams"] if w["kind"] == "billing")["next_action"], "Verify benefits")

    def test_version_is_required_on_update(self):
        maya = self.client_for(self.coordinator)
        data = maya.post("/api/clients/", {"first_name": "Ivy", "last_name": "Chen", "age_years": 3}, format="json").data
        ws = data["episodes"][0]["workstreams"][0]
        self.assertEqual(maya.patch(f"/api/clients/workstreams/{ws['id']}/", {"next_action": "x"}, format="json").status_code, 400)


class AuditHistoryTests(FoundationTestCase):
    def test_every_change_writes_history_with_actor_and_actor_type(self):
        maya = self.client_for(self.coordinator)
        data = maya.post("/api/clients/", {"first_name": "Leo", "last_name": "Park", "age_years": 6}, format="json").data
        ws = data["episodes"][0]["workstreams"][0]
        maya.patch(f"/api/clients/workstreams/{ws['id']}/", {"next_action": "Phone intake", "waiting_on": "Family", "version": ws["version"]}, format="json")
        history = maya.get(f"/api/audit/clients/{data['id']}/").data["results"]
        self.assertTrue(history)
        latest = history[0]
        self.assertEqual(latest["actor_label"], "Maya Torres")
        self.assertEqual(latest["actor_type"], "human")
        fields = {c["field"]: (c["old_value"], c["new_value"]) for c in latest["changes"]}
        self.assertEqual(fields["next_action"], ("", "Phone intake"))
        self.assertEqual(fields["waiting_on"], ("", "Family"))
        self.assertTrue(all(e["hash"] for e in history))

    def test_history_cannot_be_edited_or_deleted(self):
        maya = self.client_for(self.coordinator)
        maya.post("/api/clients/", {"first_name": "Leo", "last_name": "Park", "age_years": 6}, format="json")
        with self.as_system():
            event = AuditEvent.objects.first()
            # No UPDATE/DELETE policy exists and the table is forced under RLS, so
            # even the owning database role cannot touch a row; a trigger refuses
            # the operation as a second layer if the policies were ever dropped.
            self.assertEqual(AuditEvent.objects.filter(pk=event.pk).update(summary="tampered"), 0)
            deleted, _ = AuditEvent.objects.filter(pk=event.pk).delete()
            self.assertEqual(deleted, 0)
            event.refresh_from_db()
            self.assertNotEqual(event.summary, "tampered")
            with connection.cursor() as cur:
                cur.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = 'audit_auditevent'::regclass AND NOT tgisinternal ORDER BY 1")
                self.assertEqual([r[0] for r in cur.fetchall()], ["audit_auditevent_append_only", "audit_auditevent_no_truncate"])

    def test_system_actions_are_distinguishable_from_human_ones(self):
        maya = self.client_for(self.coordinator)
        maya.post("/api/clients/", {"first_name": "Leo", "last_name": "Park", "age_years": 6}, format="json")
        admin = self.client_for(self.admin)
        types = {e["actor_type"] for e in admin.get("/api/audit/events/").data["results"]}
        self.assertIn("human", types)
        self.assertIn("system", types)  # seed + sign-in sync entries

    def test_hash_chain_verifies(self):
        maya = self.client_for(self.coordinator)
        maya.post("/api/clients/", {"first_name": "Leo", "last_name": "Park", "age_years": 6}, format="json")
        result = self.client_for(self.admin).get("/api/audit/integrity/").data
        self.assertTrue(result["intact"], result)
