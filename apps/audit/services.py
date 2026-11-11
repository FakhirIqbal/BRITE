"""Write audit events. Every write path calls record_event()."""
from __future__ import annotations

import hashlib
import json

from django.db import connection, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.core.context import get_actor


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def _compute_hash(prev_hash: str, payload: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(payload)).encode("utf-8")).hexdigest()


def _lock_stream_and_last_hash(stream: str) -> str:
    """Serialise appends per stream (so the hash chain cannot fork) and fetch the previous hash."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s)), "
            "(SELECT hash FROM audit_auditevent WHERE stream = %s ORDER BY id DESC LIMIT 1)",
            [stream, stream],
        )
        row = cur.fetchone()
    return (row[1] if row else None) or ""


@transaction.atomic(savepoint=False)
def record_event(
    instance=None,
    *,
    event_type: str,
    action: str,
    summary: str,
    changes: list[dict] | None = None,
    reason: str = "",
    stream: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    entity_label: str | None = None,
    client_id: int | None = None,
    subject_user_id: int | None = None,
    flags: list[str] | None = None,
) -> AuditEvent:
    actor = get_actor()
    if instance is not None:
        stream = stream or instance.audit_stream()
        entity_type = entity_type or instance._meta.label_lower
        entity_id = entity_id if entity_id is not None else str(instance.pk)
        entity_label = entity_label or instance.audit_label()
        if client_id is None:
            client_id = getattr(instance, "audit_client_id", None)
            if callable(client_id):
                client_id = client_id()
    stream = stream or "system"
    last = _lock_stream_and_last_hash(stream)

    event = AuditEvent(
        event_type=event_type,
        action=action,
        summary=summary[:400],
        reason=reason or "",
        stream=stream,
        entity_type=entity_type or "",
        entity_id=entity_id or "",
        entity_label=(entity_label or "")[:200],
        client_id=client_id,
        subject_user_id=subject_user_id,
        changes=changes or [],
        actor_id=actor.user_id,
        actor_label=actor.actor_label or "System",
        actor_type=actor.actor_type,
        origin_event_id=actor.origin_event_id,
        request_id=actor.request_id,
        flags=flags or [],
        prev_hash=last,
    )
    payload = {
        "occurred_at": timezone.now().isoformat(),
        "event_type": event.event_type,
        "action": event.action,
        "summary": event.summary,
        "stream": event.stream,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "changes": event.changes,
        "actor_id": event.actor_id,
        "actor_label": event.actor_label,
        "actor_type": event.actor_type,
        "origin_event_id": event.origin_event_id,
        "flags": event.flags,
    }
    event.hash = _compute_hash(last, payload)
    event.save()
    return event


def verify_stream(stream: str) -> dict:
    """Re-walk a stream's chain; returns {'intact': bool, 'events': n, 'broken_at': id|None}."""
    prev = ""
    count = 0
    for event in AuditEvent.objects.filter(stream=stream).order_by("id"):
        count += 1
        if event.prev_hash != prev:
            return {"intact": False, "events": count, "broken_at": event.id}
        prev = event.hash
    return {"intact": True, "events": count, "broken_at": None}
