"""
Administrator-configurable status sets. Nothing in the workflow is
hard-coded to a label: workstream statuses, pipeline stages and the later
authorization / clinical / staffing vocabularies all live here.
"""
from django.db import models

from apps.core.models import VersionedModel


class StatusSet(VersionedModel):
    key = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True, default="")
    reference = models.CharField(max_length=40, blank=True, default="")  # e.g. "§2", "§7"
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name

    def audit_label(self) -> str:
        return f"Status set {self.name}"


class StatusOption(VersionedModel):
    TONE_CHOICES = [
        ("neutral", "Neutral"), ("info", "Info"), ("progress", "In progress"), ("success", "Success"),
        ("warning", "Warning"), ("danger", "Danger"),
    ]

    status_set = models.ForeignKey(StatusSet, on_delete=models.PROTECT, related_name="options")
    code = models.SlugField(max_length=60)
    label = models.CharField(max_length=120)
    tone = models.CharField(max_length=12, choices=TONE_CHOICES, default="neutral")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_terminal = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "id"]
        unique_together = [("status_set", "code")]

    def __str__(self) -> str:
        return self.label

    def audit_label(self) -> str:
        return f"Status {self.status_set.name} · {self.label}"

    def audit_stream(self) -> str:
        return f"configuration.statusset:{self.status_set_id}"


# Seeded status sets (design "Status sets"). Codes are stable; labels editable.
SEEDED_STATUS_SETS = [
    {
        "key": "referral_pipeline", "name": "Referral pipeline stages", "reference": "§3",
        "description": "Eight lifecycle markers from first contact to Active Onboarding. They never block concurrent work.",
        "options": [
            ("new_inquiry", "New Inquiry", "info"), ("contact_attempted", "Contact Attempted", "neutral"),
            ("contact_made", "Contact Made", "neutral"), ("gathering_information", "Gathering Information", "progress"),
            ("benefits_verification", "Benefits Verification", "progress"), ("family_considering", "Family Considering", "warning"),
            ("proceeding", "Proceeding", "success"), ("active_onboarding", "Active Onboarding", "success"),
        ],
    },
    {
        "key": "workstream_status", "name": "Workstream status", "reference": "§2",
        "description": "Status shown on each of the six workstream panels. Overall phase is derived, never typed.",
        "options": [
            ("not_started", "Not started", "neutral"), ("in_progress", "In progress", "progress"),
            ("waiting_on", "Waiting on", "warning"), ("awaiting_approval", "Awaiting approval", "info"),
            ("blocked", "Blocked", "danger"), ("monitoring", "Monitoring", "neutral"), ("complete", "Complete", "success"),
        ],
    },
    {
        "key": "document_disposition", "name": "Document dispositions", "reference": "§15",
        "description": "Staff disposition after a document is uploaded or received.",
        "options": [
            ("expected", "Expected", "neutral"), ("uploaded_received", "Uploaded / Received", "info"),
            ("staff_confirmed_correct", "Staff Confirmed Correct", "success"), ("needs_correction", "Needs Correction", "warning"),
            ("missing_pages", "Missing Pages", "warning"), ("superseded", "Superseded", "neutral"),
        ],
    },
    {
        "key": "authorization_status", "name": "Authorization", "reference": "§7",
        "description": "Seven statuses shared by assessment and treatment authorizations.",
        "options": [
            ("submitted", "Submitted", "info"), ("pending", "Pending", "warning"), ("additional_information", "Additional Information", "warning"),
            ("approved_as_requested", "Approved as Requested", "success"), ("approved_with_modification", "Approved With Modification / Partial", "warning"),
            ("denied", "Denied", "danger"), ("not_applicable", "N/A", "neutral"),
        ],
    },
    {
        "key": "clinical_review", "name": "Clinical review", "reference": "§9",
        "description": "Plan review loop between the clinician and the Clinical Director.",
        "options": [
            ("pending_review", "Pending Review", "info"), ("approved", "Approved", "success"),
            ("revisions_requested", "Revisions Requested", "warning"), ("resubmitted", "Resubmitted", "info"),
        ],
    },
    {
        "key": "staffing_stage", "name": "Staffing", "reference": "§10",
        "description": "Staffing search and pairing stages.",
        "options": [
            ("pipeline_searching", "Pipeline / Searching", "info"), ("potential_match", "Potential Match", "info"),
            ("rbt_contacted", "RBT Contacted", "progress"), ("accepted_tentative", "Accepted / Tentative", "progress"),
            ("ready_for_pairing", "Ready for Pairing", "warning"), ("match_confirmed", "Match Confirmed", "success"),
            ("delayed_waitlisted", "Staffing Delayed / Waitlisted", "warning"), ("closed_unable_to_staff", "Closed — Unable to Staff", "danger"),
        ],
    },
    {
        "key": "school_readiness", "name": "School readiness", "reference": "§11",
        "description": "Gates the school setting only.",
        "options": [
            ("not_applicable", "Not applicable", "neutral"), ("roi_requested", "ROI Requested", "info"), ("roi_received", "ROI Received", "progress"),
            ("roi_confirmed", "ROI Confirmed", "success"), ("school_contacted", "School Contacted", "progress"), ("school_setting_ready", "School Setting Ready", "success"),
        ],
    },
    {
        "key": "episode_closure_reason", "name": "Episode closure reasons", "reference": "§3–§4",
        "description": "Structured reasons recorded when an episode is closed by a person.",
        "options": [
            ("payer_plan_not_accepted", "Payer / plan not accepted", "neutral"), ("out_of_network_not_proceeding", "Out of network and family did not proceed", "neutral"),
            ("outside_service_area", "Outside service area", "neutral"), ("family_declined", "Family declined", "neutral"),
            ("unable_to_reach", "Unable to reach", "neutral"), ("services_completed", "Services completed / discharged", "neutral"), ("other", "Other", "neutral"),
        ],
    },
]
