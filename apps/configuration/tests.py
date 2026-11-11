from apps.core.tests.base import FoundationTestCase


class StatusConfigurationTests(FoundationTestCase):
    def test_admin_can_add_and_change_statuses_and_changes_are_audited(self):
        admin = self.client_for(self.admin)
        sets = admin.get("/api/admin/configuration/status-sets/").data
        self.assertTrue(any(s["key"] == "workstream_status" for s in sets))
        response = admin.post("/api/admin/configuration/status-sets/workstream_status/options/", {"code": "on_hold", "label": "On hold", "tone": "warning"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        option = response.data
        response = admin.patch(f"/api/admin/configuration/status-sets/workstream_status/options/{option['id']}/", {"label": "On hold (family)", "version": option["version"]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        stale = admin.patch(f"/api/admin/configuration/status-sets/workstream_status/options/{option['id']}/", {"label": "Again", "version": option["version"]}, format="json")
        self.assertEqual(stale.status_code, 409)
        events = admin.get("/api/audit/events/?event_type=configuration").data["results"]
        self.assertTrue(any("On hold" in e["summary"] for e in events))

    def test_vocabulary_readable_by_any_role_but_not_editable(self):
        billing = self.client_for(self.billing)
        vocab = billing.get("/api/vocabulary/").data
        self.assertIn("workstream_status", vocab)
        self.assertEqual(billing.post("/api/admin/configuration/status-sets/workstream_status/options/", {"code": "x", "label": "X"}).status_code, 403)

    def test_workstream_status_must_come_from_configured_set(self):
        maya = self.client_for(self.coordinator)
        data = maya.post("/api/clients/", {"first_name": "Ana", "last_name": "Ruiz", "age_years": 5}, format="json").data
        ws = data["episodes"][0]["workstreams"][0]
        response = maya.patch(f"/api/clients/workstreams/{ws['id']}/", {"status": "made_up", "version": ws["version"]}, format="json")
        self.assertEqual(response.status_code, 400)
