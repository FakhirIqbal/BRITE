"""Account and access services: sign-in, group sync, exceptions, owners."""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.accounts.access import active_exceptions, is_system_owner
from apps.accounts.google import DirectoryClient, GoogleIdentity
from apps.accounts.models import IndividualException, SystemOwner, User, WorkspaceGroupMapping, WorkspaceGroupMembership
from apps.accounts.roles import Capability, Level, Role
from apps.audit.services import record_event
from apps.core.context import ActorContext, ActorType, actor_scope, get_actor
from apps.core.exceptions import BusinessRuleViolation
from apps.core.services import actor_label

logger = logging.getLogger(__name__)

MINIMUM_SYSTEM_OWNERS = 2


# ---------------------------------------------------------------------------
# Sign-in and group membership
# ---------------------------------------------------------------------------
@transaction.atomic(savepoint=False)
def user_from_google_identity(identity: GoogleIdentity) -> User:
    user = User.objects.filter(google_sub=identity.sub).first() or User.objects.filter(email=identity.email).first()
    if user is None:
        user = User.objects.create_user(email=identity.email, full_name=identity.name, google_sub=identity.sub, picture_url=identity.picture)
        with actor_scope(ActorContext(actor_type=ActorType.SYSTEM, actor_label="Workspace sign-in")):
            record_event(
                event_type="access_change",
                action="user_created",
                summary=f"{user} signed in for the first time; account created from Workspace identity",
                stream=user.audit_stream(),
                entity_type="accounts.user",
                entity_id=str(user.pk),
                entity_label=str(user),
                subject_user_id=user.pk,
            )
    else:
        changed = False
        if not user.google_sub:
            user.google_sub = identity.sub
            changed = True
        if identity.name and user.full_name != identity.name:
            user.full_name = identity.name
            changed = True
        if identity.picture and user.picture_url != identity.picture:
            user.picture_url = identity.picture
            changed = True
        if changed:
            user.save(update_fields=["google_sub", "full_name", "picture_url"])
    if not user.is_active:
        raise PermissionError("This account has been deactivated.")
    return user


def sync_group_memberships(user: User, group_emails: list[str], source: str) -> dict:
    """Reconcile the user's memberships of *mapped* groups with the given list."""
    now = timezone.now()
    wanted = set(e.lower() for e in group_emails)
    mappings = {m.group_email.lower(): m for m in WorkspaceGroupMapping.objects.filter(is_active=True)}
    added, removed = [], []
    with actor_scope(ActorContext(actor_type=ActorType.SYSTEM, actor_label="Workspace group sync", bypass_rls=get_actor().bypass_rls)):
        current = {m.group.group_email.lower(): m for m in WorkspaceGroupMembership.objects.filter(user=user, removed_at__isnull=True).select_related("group")}
        for email, mapping in mappings.items():
            if email in wanted and email not in current:
                WorkspaceGroupMembership.objects.create(user=user, group=mapping, source=source, synced_at=now)
                added.append(mapping)
            elif email not in wanted and email in current and source == WorkspaceGroupMembership.SOURCE_DIRECTORY:
                membership = current[email]
                membership.removed_at = now
                membership.save(update_fields=["removed_at"])
                removed.append(mapping)
        for mapping in added:
            record_event(
                event_type="access_change", action="group_added",
                summary=f"{user} added to {mapping.group_email} → role {Role.LABELS[mapping.role]}",
                stream=user.audit_stream(), entity_type="accounts.user", entity_id=str(user.pk),
                entity_label=str(user), subject_user_id=user.pk,
            )
        for mapping in removed:
            record_event(
                event_type="access_change", action="group_removed",
                summary=f"{user} removed from {mapping.group_email} → role {Role.LABELS[mapping.role]} withdrawn",
                stream=user.audit_stream(), entity_type="accounts.user", entity_id=str(user.pk),
                entity_label=str(user), subject_user_id=user.pk,
            )
    user.last_group_sync_at = now
    user.save(update_fields=["last_group_sync_at"])
    return {"added": [m.group_email for m in added], "removed": [m.group_email for m in removed]}


def sync_from_directory(user: User) -> dict | None:
    """Pull the user's groups from the Workspace Directory if configured."""
    if not DirectoryClient.is_configured():
        return None
    try:
        groups = DirectoryClient().groups_for_user(user.email)
    except Exception:  # network / permission problems must not block sign-in
        logger.exception("Directory group sync failed for %s", user.email)
        return None
    return sync_group_memberships(user, groups, WorkspaceGroupMembership.SOURCE_DIRECTORY)


def record_sign_in(user: User) -> None:
    user.last_sign_in_at = timezone.now()
    user.save(update_fields=["last_sign_in_at"])


# ---------------------------------------------------------------------------
# Manual membership (administrator recorded) — audited as an access change
# ---------------------------------------------------------------------------
@transaction.atomic(savepoint=False)
def set_manual_membership(user: User, mapping: WorkspaceGroupMapping, member: bool) -> None:
    now = timezone.now()
    current = WorkspaceGroupMembership.objects.filter(user=user, group=mapping, removed_at__isnull=True).first()
    if member and current is None:
        WorkspaceGroupMembership.objects.create(user=user, group=mapping, source=WorkspaceGroupMembership.SOURCE_MANUAL, synced_at=now)
        record_event(
            event_type="access_change", action="group_added",
            summary=f"{user} recorded as member of {mapping.group_email} → role {Role.LABELS[mapping.role]}",
            stream=user.audit_stream(), entity_type="accounts.user", entity_id=str(user.pk), entity_label=str(user), subject_user_id=user.pk,
        )
    elif not member and current is not None:
        current.removed_at = now
        current.save(update_fields=["removed_at"])
        record_event(
            event_type="access_change", action="group_removed",
            summary=f"{user} removed from {mapping.group_email} → role {Role.LABELS[mapping.role]} withdrawn",
            stream=user.audit_stream(), entity_type="accounts.user", entity_id=str(user.pk), entity_label=str(user), subject_user_id=user.pk,
        )


# ---------------------------------------------------------------------------
# Individual exceptions
# ---------------------------------------------------------------------------
def _other_owner_emails(exclude_user: User) -> list[str]:
    return list(
        SystemOwner.objects.filter(removed_at__isnull=True).exclude(user=exclude_user).values_list("user__email", flat=True)
    )


@transaction.atomic(savepoint=False)
def add_exception(*, target: User, actor: User, capability: str, kind: str, level: str = Level.VIEW, reason: str = "", duration: str = IndividualException.DURATION_PERMANENT, expires_on=None) -> IndividualException:
    if capability not in Capability.LABELS:
        raise BusinessRuleViolation("Unknown capability group.")
    if kind not in {IndividualException.KIND_GRANT, IndividualException.KIND_REMOVE}:
        raise BusinessRuleViolation("Type must be grant or remove.")
    if kind == IndividualException.KIND_GRANT and level not in {Level.VIEW, Level.EDIT}:
        raise BusinessRuleViolation("Choose View or Edit for a grant.")
    if not reason or not reason.strip():
        raise BusinessRuleViolation("A reason is required.")
    if duration == IndividualException.DURATION_TEMPORARY:
        if not expires_on:
            raise BusinessRuleViolation("A temporary grant needs an expiry date.")
        if expires_on <= timezone.localdate():
            raise BusinessRuleViolation("The expiry date must be in the future.")
    else:
        expires_on = None

    self_granted = target.pk == actor.pk
    notified: list[str] = []
    if self_granted:
        notified = _other_owner_emails(actor)
    exc = IndividualException.objects.create(
        user=target, capability=capability, kind=kind,
        level=level if kind == IndividualException.KIND_GRANT else Level.NONE,
        reason=reason.strip(), duration=duration, expires_on=expires_on,
        granted_by=actor, granted_by_label=str(actor), is_self_granted=self_granted,
        notified_owner_emails=notified, created_by=actor, updated_by=actor, updated_by_label=str(actor),
    )
    verb = "granted" if kind == IndividualException.KIND_GRANT else "removed"
    until = f" · until {expires_on:%b %-d, %Y}" if expires_on else ""
    summary = (
        f"Exception {verb} {'to self' if self_granted else target} · {Capability.LABELS[capability]} · "
        f"{Level.LABELS[exc.level] if kind == IndividualException.KIND_GRANT else 'None'}{until} · reason: {exc.reason}"
    )
    flags = ["self_granted"] if self_granted else []
    record_event(
        exc, event_type="access_change", action=f"exception_{verb}", summary=summary, reason=exc.reason,
        subject_user_id=target.pk, flags=flags,
        changes=[{"field": capability, "old_value": None, "new_value": f"{kind}:{exc.level}"}],
    )
    if self_granted and notified:
        try:
            send_mail(
                subject="BRITE · Self-granted access change",
                message=(
                    f"{actor} changed their own access: {Capability.LABELS[capability]} · {verb} · "
                    f"{Level.LABELS[exc.level]}{until}.\nReason: {exc.reason}\n\nSign in to BRITE to review the audit history."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=notified,
                fail_silently=True,
            )
        except Exception:  # never block the save on email delivery
            logger.exception("Could not send self-grant notification")
    return exc


@transaction.atomic(savepoint=False)
def remove_exception(exc: IndividualException, *, actor_desc: str, reason: str = "", scheduled: bool = False) -> IndividualException:
    if exc.removed_at:
        return exc
    exc.removed_at = timezone.now()
    exc.removed_reason = reason
    exc.removed_by_label = actor_desc
    exc.save(update_fields=["removed_at", "removed_reason", "removed_by_label"])
    record_event(
        exc, event_type="access_change", action="exception_removed",
        summary=(
            f"Temporary grant expired and removed · {exc.user} · {Capability.LABELS[exc.capability]} · {Level.LABELS.get(exc.level, exc.level)}"
            f" (granted by {exc.granted_by_label} {exc.created_at:%b %-d})"
            if scheduled else
            f"Exception ended · {exc.user} · {Capability.LABELS[exc.capability]}" + (f" · reason: {reason}" if reason else "")
        ),
        reason=reason, subject_user_id=exc.user_id,
        changes=[{"field": exc.capability, "old_value": f"{exc.kind}:{exc.level}", "new_value": None}],
    )
    return exc


def expire_temporary_grants() -> int:
    """Scheduled job: remove expired temporary grants, audited as a scheduled action."""
    today = timezone.localdate()
    expired = IndividualException.objects.filter(
        removed_at__isnull=True, duration=IndividualException.DURATION_TEMPORARY, expires_on__lt=today
    )
    count = 0
    for exc in expired:
        remove_exception(exc, actor_desc="Scheduled job", reason="Expired", scheduled=True)
        count += 1
    return count


# ---------------------------------------------------------------------------
# System Owners
# ---------------------------------------------------------------------------
def active_system_owners():
    return SystemOwner.objects.filter(removed_at__isnull=True).select_related("user").order_by("assigned_at")


@transaction.atomic(savepoint=False)
def add_system_owner(user: User, *, assigned_by: str) -> SystemOwner:
    if is_system_owner(user):
        raise BusinessRuleViolation(f"{user} is already a System Owner.")
    owner = SystemOwner.objects.create(user=user, assigned_by_label=assigned_by)
    record_event(
        owner, event_type="access_change", action="system_owner_added",
        summary=f"{user} assigned as System Owner", subject_user_id=user.pk,
        changes=[{"field": "system_owner", "old_value": "No", "new_value": "Yes"}],
    )
    return owner


@transaction.atomic(savepoint=False)
def remove_system_owner(owner: SystemOwner, *, removed_by: str) -> SystemOwner:
    remaining = active_system_owners().exclude(pk=owner.pk).count()
    if remaining < MINIMUM_SYSTEM_OWNERS:
        record_event(
            owner, event_type="access_change", action="system_owner_removal_blocked",
            summary=f"Blocked: removing a System Owner would leave fewer than {MINIMUM_SYSTEM_OWNERS} ({owner.user})",
            subject_user_id=owner.user_id,
        )
        raise BusinessRuleViolation(
            f"BRITE needs at least {MINIMUM_SYSTEM_OWNERS} System Owners. Removing {owner.user} would leave {remaining}. "
            "Add another System Owner first, then remove this one."
        )
    owner.removed_at = timezone.now()
    owner.removed_by_label = removed_by
    owner.save(update_fields=["removed_at", "removed_by_label"])
    record_event(
        owner, event_type="access_change", action="system_owner_removed",
        summary=f"{owner.user} removed as System Owner", subject_user_id=owner.user_id,
        changes=[{"field": "system_owner", "old_value": "Yes", "new_value": "No"}],
    )
    return owner
