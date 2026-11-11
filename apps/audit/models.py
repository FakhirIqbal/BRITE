"""
Append-only audit history.

One AuditEvent per action (with its field changes inline) carrying actor
identity, actor type (human / system / scheduled) and the originating human
event for automated actions. Each stream (one record) is a hash chain: every
event stores the previous hash and its own hash, so edits are evident.
A database trigger refuses UPDATE and DELETE on this table.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.context import ActorType


class AuditEvent(models.Model):
    EVENT_TYPES = [
        ("record_change", "Record change"),
        ("access_change", "Access change"),
        ("document_access", "Document access"),
        ("sign_in", "Sign-in"),
        ("configuration", "Configuration"),
    ]

    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    event_type = models.CharField(max_length=32, choices=EVENT_TYPES, db_index=True)
    action = models.CharField(max_length=40)  # created, updated, closed, granted, removed, ...
    summary = models.CharField(max_length=400)
    reason = models.TextField(blank=True, default="")

    # What was touched.
    stream = models.CharField(max_length=120, db_index=True)  # e.g. clients.client:12
    entity_type = models.CharField(max_length=80, db_index=True)  # e.g. clients.workstream
    entity_id = models.CharField(max_length=40, blank=True, default="")
    entity_label = models.CharField(max_length=200, blank=True, default="")
    # The client record this event relates to, when any (for the record History tab).
    client_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    # The person this event relates to, when any (access changes).
    subject_user_id = models.BigIntegerField(null=True, blank=True, db_index=True)

    # Field-level changes: [{field, old_value, new_value}]
    changes = models.JSONField(default=list, blank=True)

    # Who.
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    actor_label = models.CharField(max_length=160)
    actor_type = models.CharField(max_length=10, choices=ActorType.CHOICES)
    origin_event = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="caused_events")
    request_id = models.CharField(max_length=32, blank=True, default="")
    flags = models.JSONField(default=list, blank=True)  # e.g. ["self_granted"]

    # Tamper evidence.
    prev_hash = models.CharField(max_length=64, blank=True, default="")
    hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [models.Index(fields=["stream", "id"])]

    def __str__(self) -> str:
        return f"{self.occurred_at:%Y-%m-%d %H:%M} · {self.actor_label} · {self.summary}"
