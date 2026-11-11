"""DRF permission classes built on capability groups."""
from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import Level


def _caps(request) -> dict[str, str]:
    ctx = getattr(request, "actor_context", None)
    return ctx.capabilities if ctx else {}


class HasCapability(BasePermission):
    """
    Requires `capability` at `view_level` for safe methods and `edit_level`
    for writes. Subclass or use `capability_permission()` to configure.
    """

    capability: str = ""
    view_level: str = Level.VIEW
    edit_level: str = Level.EDIT
    message = "Your role doesn't include this capability group and no exception has been granted."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        held = _caps(request).get(self.capability, Level.NONE)
        required = self.view_level if request.method in SAFE_METHODS else self.edit_level
        return Level.satisfies(held, required)


def capability_permission(capability: str, *, view_level: str = Level.VIEW, edit_level: str = Level.EDIT):
    return type(
        f"Requires_{capability}",
        (HasCapability,),
        {"capability": capability, "view_level": view_level, "edit_level": edit_level},
    )


class IsSystemOwner(BasePermission):
    message = "Only a System Owner can do this."

    def has_permission(self, request, view):
        from apps.accounts.access import is_system_owner

        return bool(request.user and request.user.is_authenticated and is_system_owner(request.user))
