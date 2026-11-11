"""
Core client schema: Client → Service Episode → six Workstreams.

* Client carries the permanent System Client ID (BC-000001…, from a database
  sequence, never reused) and a unique searchable Client Code Name.
* One active Service Episode per client is enforced by a partial unique index;
  episodes are numbered sequentially and a closed episode is read-only.
* Every episode has all six workstreams from the moment it is created, each
  with Status · Owner · Next Action · Due Date · Blocker · Waiting On · Last Updated.
* There is no writable overall status: phase and journey are derived.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import VersionedModel


class Client(VersionedModel):
    STATE_CHOICES = [("FL", "Florida"), ("TX", "Texas")]

    client_id = models.CharField(max_length=12, unique=True, editable=False)  # BC-000142
    code_name = models.CharField(max_length=60, unique=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    date_of_birth = models.DateField(null=True, blank=True)
    age_years = models.PositiveSmallIntegerField(null=True, blank=True)  # age may be collected before DOB
    state_market = models.CharField(max_length=2, choices=STATE_CHOICES, default="FL")
    drive_folder_url = models.URLField(blank=True, default="")
    drive_folder_id = models.CharField(max_length=120, blank=True, default="")
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["last_name", "first_name"]), models.Index(fields=["code_name"])]

    def __str__(self) -> str:
        return f"{self.code_name} · {self.client_id}"

    def audit_label(self) -> str:
        return f"Client {self.code_name} · {self.client_id}"

    def audit_stream(self) -> str:
        return f"clients.client:{self.pk}"

    @property
    def audit_client_id(self) -> int:
        return self.pk

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def _episode_list(self):
        cache = getattr(self, "_prefetched_objects_cache", {})
        return cache.get("episodes") if "episodes" in cache else None

    @property
    def active_episode(self):
        episodes = self._episode_list()
        if episodes is not None:
            return next((e for e in episodes if e.state == ServiceEpisode.STATE_OPEN), None)
        return self.episodes.filter(state=ServiceEpisode.STATE_OPEN).first()

    @property
    def record_state(self) -> str:
        """Potential / Active / Closed / Archived — derived, never typed."""
        if self.is_archived:
            return "archived"
        episode = self.active_episode
        if episode is None:
            episodes = self._episode_list()
            has_any = bool(episodes) if episodes is not None else self.episodes.exists()
            return "closed" if has_any else "potential"
        return episode.lifecycle


class ServiceEpisode(VersionedModel):
    STATE_OPEN = "open"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [(STATE_OPEN, "Open"), (STATE_CLOSED, "Closed")]

    # Lifecycle markers available at this foundation stage. Later milestones
    # derive the full journey from workstream data; the field is never user-typed.
    LIFECYCLE_POTENTIAL = "potential"
    LIFECYCLE_ACTIVE = "active"
    LIFECYCLE_CHOICES = [(LIFECYCLE_POTENTIAL, "Potential"), (LIFECYCLE_ACTIVE, "Active")]

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="episodes")
    number = models.PositiveSmallIntegerField()
    state = models.CharField(max_length=8, choices=STATE_CHOICES, default=STATE_OPEN)
    lifecycle = models.CharField(max_length=12, choices=LIFECYCLE_CHOICES, default=LIFECYCLE_POTENTIAL, editable=False)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by_label = models.CharField(max_length=160, blank=True, default="")
    closure_reason = models.CharField(max_length=60, blank=True, default="")  # code from the closure-reason status set
    closure_note = models.TextField(blank=True, default="")
    settings_requested = models.JSONField(default=list, blank=True)  # e.g. ["home", "school"]

    class Meta:
        ordering = ["client", "number"]
        constraints = [
            models.UniqueConstraint(fields=["client", "number"], name="uniq_episode_number_per_client"),
            models.UniqueConstraint(fields=["client"], condition=models.Q(state="open"), name="uniq_one_open_episode_per_client"),
        ]

    def __str__(self) -> str:
        return f"{self.client.code_name} · Episode {self.number}"

    def audit_label(self) -> str:
        return f"Episode {self.number} of {self.client.code_name}"

    def audit_stream(self) -> str:
        return f"clients.client:{self.client_id}"

    @property
    def audit_client_id(self) -> int:
        return self.client_id

    @property
    def is_open(self) -> bool:
        return self.state == self.STATE_OPEN

    def clean(self):
        if self.state == self.STATE_CLOSED and not self.closure_reason:
            raise ValidationError({"closure_reason": "A structured closure reason is required to close an episode."})

    # Journey markers (design: ten steps). Derived from episode + workstream data.
    JOURNEY = [
        ("potential_client", "Potential Client"),
        ("active_onboarding", "Active Onboarding"),
        ("assessment_readiness", "Assessment Readiness"),
        ("assessment_authorization", "Assessment Authorization (if applicable)"),
        ("assessment_treatment_plan", "Assessment / Treatment Plan"),
        ("treatment_authorization", "Treatment Authorization"),
        ("staffing_readiness", "Staffing / Readiness"),
        ("service_start", "Service Start"),
        ("stabilization", "Stabilization"),
        ("ongoing_services", "Ongoing Services"),
    ]

    def derived_journey_phase(self) -> str:
        """
        Foundation derivation: the phase follows the data that exists at this
        stage. Later milestones extend the derivation with authorization,
        clinical, staffing and start data; nothing here is user-typed.
        """
        if self.lifecycle == self.LIFECYCLE_ACTIVE:
            return "active_onboarding"
        return "potential_client"


class Workstream(VersionedModel):
    KIND_CLIENT_COORDINATION = "client_coordination"
    KIND_BILLING = "billing"
    KIND_CLINICAL = "clinical"
    KIND_HR_STAFFING = "hr_staffing"
    KIND_SCHOOL_READINESS = "school_readiness"
    KIND_OPERATIONS = "operations"
    KIND_CHOICES = [
        (KIND_CLIENT_COORDINATION, "Client Coordination"),
        (KIND_BILLING, "Billing / Benefits & Authorization"),
        (KIND_CLINICAL, "Clinical"),
        (KIND_HR_STAFFING, "HR / Staffing"),
        (KIND_SCHOOL_READINESS, "School Readiness"),
        (KIND_OPERATIONS, "Operations"),
    ]
    KIND_ORDER = [k for k, _ in KIND_CHOICES]
    KIND_LABELS = dict(KIND_CHOICES)
    # Which role is responsible for monitoring an unowned workstream.
    KIND_MONITOR_ROLE = {
        KIND_CLIENT_COORDINATION: "client_coordinator", KIND_BILLING: "billing", KIND_CLINICAL: "clinical_director",
        KIND_HR_STAFFING: "hr_staffing", KIND_SCHOOL_READINESS: "hr_staffing", KIND_OPERATIONS: "operations",
    }

    episode = models.ForeignKey(ServiceEpisode, on_delete=models.PROTECT, related_name="workstreams")
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    status = models.CharField(max_length=60, default="not_started")  # code from the workstream_status set
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="owned_workstreams")
    next_action = models.CharField(max_length=300, blank=True, default="")
    due_date = models.DateField(null=True, blank=True)
    blocker = models.CharField(max_length=300, blank=True, default="")
    waiting_on = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["episode", "id"]
        constraints = [models.UniqueConstraint(fields=["episode", "kind"], name="uniq_workstream_kind_per_episode")]

    def __str__(self) -> str:
        return f"{self.episode} · {self.KIND_LABELS[self.kind]}"

    def audit_label(self) -> str:
        return f"{self.KIND_LABELS[self.kind]} workstream · {self.episode.client.code_name}"

    def audit_stream(self) -> str:
        return f"clients.client:{self.episode.client_id}"

    @property
    def audit_client_id(self) -> int:
        return self.episode.client_id

    @property
    def is_unassigned(self) -> bool:
        return self.owner_id is None
