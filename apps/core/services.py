"""
The single write path for versioned, audited records.

save_versioned() applies field changes with an optimistic-concurrency check
(UPDATE ... WHERE version = expected). If no row matches, someone else saved
first and a ConcurrencyConflict is raised naming who and when. Every applied
field change is written to the append-only audit history.
"""
from __future__ import annotations

from typing import Any

from django.db import models, transaction
from django.utils import timezone

from apps.core.context import ActorType, get_actor
from apps.core.exceptions import ConcurrencyConflict


def _actor_user():
    from apps.accounts.models import User

    actor = get_actor()
    if actor.user_id is None:
        return None
    if actor.user is None or getattr(actor.user, "pk", None) != actor.user_id:
        actor.user = User.objects.filter(pk=actor.user_id).first()
    return actor.user


def actor_label() -> str:
    actor = get_actor()
    if actor.actor_type == ActorType.HUMAN and actor.actor_label:
        return actor.actor_label
    return actor.actor_label or "System"


def _serialize(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, models.Model):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@transaction.atomic(savepoint=False)
def create_versioned(model: type[models.Model], *, event_type: str = "record_change", summary: str = "", **fields):
    """Create a record and write a creation entry per populated field."""
    from apps.audit.services import record_event

    user = _actor_user()
    instance = model(**fields)
    instance.created_by = user
    instance.updated_by = user
    instance.updated_by_label = actor_label()
    # Uniqueness is enforced by database constraints; skip the extra lookups.
    instance.full_clean(exclude=["created_by", "updated_by"], validate_unique=False)
    instance.save()
    changes = []
    for name, value in fields.items():
        if value in (None, "", []):
            continue
        changes.append({"field": name, "old_value": None, "new_value": _serialize(getattr(instance, name))})
    record_event(
        instance,
        event_type=event_type,
        action="created",
        summary=summary or f"{instance.audit_label()} created",
        changes=changes,
    )
    return instance


@transaction.atomic(savepoint=False)
def save_versioned(
    instance: models.Model,
    changes: dict[str, Any],
    *,
    expected_version: int | None,
    event_type: str = "record_change",
    summary: str = "",
    reason: str = "",
):
    """
    Apply `changes` to `instance` only if its stored version equals
    `expected_version`. Returns the refreshed instance.
    """
    from apps.audit.services import record_event

    model = type(instance)
    if expected_version is None:
        expected_version = instance.version

    old_values = {name: getattr(instance, name) for name in changes}
    real_changes = {name: value for name, value in changes.items() if old_values[name] != value}
    if not real_changes:
        return instance

    user = _actor_user()
    now = timezone.now()
    label = actor_label()
    update_fields = dict(real_changes)
    update_fields.update(
        version=expected_version + 1,
        updated_at=now,
        updated_by=user,
        updated_by_label=label,
    )

    # Validate the would-be state before touching the database.
    for name, value in real_changes.items():
        setattr(instance, name, value)
    instance.full_clean(exclude=["created_by", "updated_by"], validate_unique=False)

    updated = model.objects.filter(pk=instance.pk, version=expected_version).update(**update_fields)
    if updated != 1:
        current = model.objects.filter(pk=instance.pk).values("version", "updated_at", "updated_by_label").first()
        raise ConcurrencyConflict(
            changed_by=(current or {}).get("updated_by_label") or "another user",
            changed_at=(current or {}).get("updated_at"),
            current_version=(current or {}).get("version") or expected_version,
            record_label=instance.audit_label(),
        )

    instance.refresh_from_db()
    record_event(
        instance,
        event_type=event_type,
        action="updated",
        summary=summary or f"{instance.audit_label()} updated",
        reason=reason,
        changes=[
            {"field": name, "old_value": _serialize(old_values[name]), "new_value": _serialize(getattr(instance, name))}
            for name in real_changes
        ],
    )
    return instance
