"""Effective-access computation: role defaults → individual exceptions → result."""
from __future__ import annotations

from django.utils import timezone

from apps.accounts.models import IndividualException, RoleCapabilityDefault, SystemOwner, User, WorkspaceGroupMembership
from apps.accounts.roles import EXCEPTION_SECTIONS, SECTION_REGISTRY, Capability, Level, Role


def user_roles(user: User) -> list[str]:
    roles = set(
        WorkspaceGroupMembership.objects.filter(user=user, removed_at__isnull=True, group__is_active=True)
        .values_list("group__role", flat=True)
    )
    return [r for r in Role.ORDER if r in roles]


def role_defaults_matrix() -> dict[str, dict[str, str]]:
    matrix: dict[str, dict[str, str]] = {role: {cap: Level.NONE for cap in Capability.ORDER} for role in Role.ORDER}
    for row in RoleCapabilityDefault.objects.all():
        matrix.setdefault(row.role, {})[row.capability] = row.level
    return matrix


def active_exceptions(user: User) -> list[IndividualException]:
    today = timezone.localdate()
    rows = IndividualException.objects.filter(user=user, removed_at__isnull=True).order_by("created_at")
    return [row for row in rows if not (row.duration == IndividualException.DURATION_TEMPORARY and row.expires_on and row.expires_on < today)]


def effective_access_detail(user: User) -> dict:
    """Per-capability breakdown used by the Effective access screen and the API."""
    roles = user_roles(user)
    matrix = role_defaults_matrix()
    exceptions = active_exceptions(user)
    rows = []
    effective: dict[str, str] = {}
    for cap in Capability.ORDER:
        from_roles = Level.highest(*(matrix.get(role, {}).get(cap, Level.NONE) for role in roles))
        exc_rows = [e for e in exceptions if e.capability == cap]
        removal = next((e for e in reversed(exc_rows) if e.kind == IndividualException.KIND_REMOVE), None)
        grants = [e for e in exc_rows if e.kind == IndividualException.KIND_GRANT]
        if removal is not None:
            result = Level.NONE
        else:
            result = Level.highest(from_roles, *(g.level for g in grants))
        effective[cap] = result
        rows.append(
            {
                "capability": cap,
                "label": Capability.LABELS[cap],
                "from_roles": from_roles,
                "exceptions": [
                    {
                        "id": e.id,
                        "kind": e.kind,
                        "level": e.level,
                        "reason": e.reason,
                        "duration": e.duration,
                        "expires_on": e.expires_on,
                        "granted_by": e.granted_by_label,
                        "granted_on": e.created_at,
                        "is_self_granted": e.is_self_granted,
                    }
                    for e in exc_rows
                ],
                "effective": result,
            }
        )
    return {"roles": roles, "rows": rows, "effective": effective}


def effective_capabilities(user: User) -> dict[str, str]:
    return effective_access_detail(user)["effective"]


def is_system_owner(user: User) -> bool:
    return SystemOwner.objects.filter(user=user, removed_at__isnull=True).exists()


def navigation_for(user: User, capabilities: dict[str, str] | None = None, roles: list[str] | None = None) -> list[dict]:
    """Sidebar groups for the user's roles, limited to enabled sections they can enter."""
    roles = roles if roles is not None else user_roles(user)
    caps = capabilities if capabilities is not None else effective_capabilities(user)
    groups: list[dict] = []
    seen: set[str] = set()
    for role in roles:
        for group in SECTION_REGISTRY.get(role, ()):
            items = []
            for section in group.sections:
                if not section.enabled or section.key in seen:
                    continue  # a section shared by several roles (e.g. Home, Clients) is listed once
                if section.capability and not Level.satisfies(caps.get(section.capability, Level.NONE), section.level):
                    continue
                items.append({"key": section.key, "label": section.label, "path": section.path, "icon": section.icon})
                seen.add(section.key)
            if items:
                groups.append({"role": role, "role_label": Role.LABELS[role], "label": group.label, "items": items})
    # Areas reachable through an individual exception only.
    extra = []
    for cap, section in EXCEPTION_SECTIONS.items():
        if section.key in seen:
            continue
        if Level.satisfies(caps.get(cap, Level.NONE), section.level):
            extra.append({"key": section.key, "label": section.label, "path": section.path, "icon": section.icon})
    if extra:
        groups.append({"role": None, "role_label": None, "label": "Through an exception", "items": extra})
    return groups
