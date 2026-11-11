"""Administration: users & access, exceptions, System Owners, Workspace groups."""
from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts import services
from apps.accounts.access import effective_access_detail, is_system_owner, role_defaults_matrix, user_roles
from apps.accounts.models import IndividualException, RoleCapabilityDefault, SystemOwner, User, WorkspaceGroupMapping, WorkspaceGroupMembership
from apps.accounts.permissions import IsSystemOwner, capability_permission
from apps.accounts.roles import Capability, Level, Role
from apps.accounts.serializers import (
    ExceptionCreateSerializer, IndividualExceptionSerializer, RoleCapabilityDefaultSerializer, SystemOwnerSerializer,
    UserSummarySerializer, WorkspaceGroupMappingSerializer,
)
from apps.audit.models import AuditEvent
from apps.core.exceptions import BusinessRuleViolation
from apps.core.services import create_versioned, save_versioned
from apps.core.views import BriteAPIView, BriteViewSet

AdminConfig = capability_permission(Capability.ADMINISTRATIVE_CONFIGURATION)


def _user_row(user: User, owners: set[int], matrix: dict) -> dict:
    exceptions = [e for e in user.access_exceptions.all() if e.is_active]
    grants = sum(1 for e in exceptions if e.kind == IndividualException.KIND_GRANT)
    removals = sum(1 for e in exceptions if e.kind == IndividualException.KIND_REMOVE)
    next_expiry = min((e.expires_on for e in exceptions if e.expires_on), default=None)
    roles = sorted({m.group.role for m in user.group_memberships.all() if m.removed_at is None and m.group.is_active}, key=Role.ORDER.index)
    return {
        "id": user.pk, "email": user.email, "full_name": user.full_name, "initials": user.initials, "is_active": user.is_active,
        "roles": [{"code": r, "label": Role.LABELS[r]} for r in roles],
        "is_system_owner": user.pk in owners,
        "grants": grants, "removals": removals,
        "self_granted": any(e.is_self_granted for e in exceptions),
        "next_expiry": next_expiry,
        "last_sign_in_at": user.last_sign_in_at,
    }


class AdminOverviewView(BriteAPIView):
    permission_classes = [IsAuthenticated, AdminConfig]

    def get(self, request):
        today = timezone.localdate()
        soon = today + timezone.timedelta(days=3)
        active_exceptions = [e for e in IndividualException.objects.filter(removed_at__isnull=True) if e.is_active]
        expiring = [e for e in active_exceptions if e.expires_on and e.expires_on <= soon]
        return Response({
            "system_owners": services.active_system_owners().count(),
            "minimum_system_owners": services.MINIMUM_SYSTEM_OWNERS,
            "active_users": User.objects.filter(is_active=True).count(),
            "individual_exceptions": len(active_exceptions),
            "temporary_grants": sum(1 for e in active_exceptions if e.duration == IndividualException.DURATION_TEMPORARY),
            "expiring_soon": IndividualExceptionSerializer(expiring, many=True).data,
            "workspace_groups": WorkspaceGroupMapping.objects.filter(is_active=True).count(),
            "audit_events": AuditEvent.objects.count(),
            "recent_access_changes": [
                {"id": e.id, "occurred_at": e.occurred_at, "actor_label": e.actor_label, "actor_type": e.actor_type, "summary": e.summary, "flags": e.flags}
                for e in AuditEvent.objects.filter(event_type="access_change")[:8]
            ],
        })


class UsersAccessViewSet(BriteViewSet):
    permission_classes = [IsAuthenticated, AdminConfig]

    def get_queryset(self):
        return (
            User.objects.prefetch_related("group_memberships__group", "access_exceptions")
            .order_by("full_name", "email")
        )

    def list(self, request):
        owners = set(services.active_system_owners().values_list("user_id", flat=True))
        matrix = role_defaults_matrix()
        qs = self.get_queryset()
        search = request.query_params.get("q", "").strip()
        if search:
            qs = qs.filter(Q(full_name__icontains=search) | Q(email__icontains=search))
        rows = [_user_row(u, owners, matrix) for u in qs]
        role = request.query_params.get("role")
        if role and role != "all":
            rows = [r for r in rows if any(x["code"] == role for x in r["roles"])]
        if request.query_params.get("exceptions_only") in {"1", "true"}:
            rows = [r for r in rows if r["grants"] or r["removals"]]
        return Response({
            "results": rows,
            "stats": {
                "active_users": User.objects.filter(is_active=True).count(),
                "system_owners": len(owners),
                "individual_exceptions": sum(r["grants"] + r["removals"] for r in rows),
                "temporary_grants": sum(1 for r in rows if r["next_expiry"]),
            },
        })

    def retrieve(self, request, pk=None):
        user = self.get_queryset().filter(pk=pk).first()
        if user is None:
            return Response({"code": "not_found", "detail": "User not found."}, status=404)
        detail = effective_access_detail(user)
        memberships = user.group_memberships.filter(removed_at__isnull=True).select_related("group")
        role_rows = []
        for code in Role.ORDER:
            groups = [m.group.group_email for m in memberships if m.group.role == code and m.group.is_active]
            role_rows.append({"code": code, "label": Role.LABELS[code], "held": bool(groups), "groups": groups})
        owner = services.active_system_owners().filter(user=user).exists()
        history = AuditEvent.objects.filter(subject_user_id=user.pk, event_type="access_change")[:20]
        return Response({
            "user": UserSummarySerializer(user).data | {"last_sign_in_at": user.last_sign_in_at, "last_group_sync_at": user.last_group_sync_at},
            "roles": role_rows,
            "is_system_owner": owner,
            "access": detail["rows"],
            "effective": detail["effective"],
            "exceptions": IndividualExceptionSerializer(user.access_exceptions.all(), many=True).data,
            "history": [
                {"id": e.id, "occurred_at": e.occurred_at, "actor_label": e.actor_label, "actor_type": e.actor_type, "summary": e.summary, "flags": e.flags}
                for e in history
            ],
            "all_groups": WorkspaceGroupMappingSerializer(WorkspaceGroupMapping.objects.filter(is_active=True), many=True).data,
            "memberships": [{"group_id": m.group_id, "source": m.source, "synced_at": m.synced_at} for m in memberships],
        })

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, AdminConfig, IsSystemOwner])
    def exceptions(self, request, pk=None):
        target = User.objects.filter(pk=pk).first()
        if target is None:
            return Response({"code": "not_found", "detail": "User not found."}, status=404)
        serializer = ExceptionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exc = services.add_exception(target=target, actor=request.user, **serializer.validated_data)
        return Response(IndividualExceptionSerializer(exc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="memberships", permission_classes=[IsAuthenticated, AdminConfig, IsSystemOwner])
    def memberships(self, request, pk=None):
        """Record or end a Workspace group membership for environments without Directory sync."""
        target = User.objects.filter(pk=pk).first()
        mapping = WorkspaceGroupMapping.objects.filter(pk=request.data.get("group_id"), is_active=True).first()
        if target is None or mapping is None:
            return Response({"code": "not_found", "detail": "User or group not found."}, status=404)
        member = bool(request.data.get("member", True))
        services.set_manual_membership(target, mapping, member)
        return Response({"roles": user_roles(target)})

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated, AdminConfig, IsSystemOwner])
    def invite(self, request):
        """Create a user record ahead of first sign-in so group membership can be recorded."""
        email = (request.data.get("email") or "").strip().lower()
        full_name = (request.data.get("full_name") or "").strip()
        if not email or "@" not in email:
            raise BusinessRuleViolation("A valid email is required.")
        if User.objects.filter(email=email).exists():
            raise BusinessRuleViolation("A user with that email already exists.")
        user = User.objects.create_user(email=email, full_name=full_name)
        from apps.audit.services import record_event

        record_event(
            event_type="access_change", action="user_created", summary=f"{user} added ahead of first sign-in",
            stream=user.audit_stream(), entity_type="accounts.user", entity_id=str(user.pk), entity_label=str(user), subject_user_id=user.pk,
        )
        return Response(UserSummarySerializer(user).data, status=201)


class ExceptionViewSet(BriteViewSet):
    permission_classes = [IsAuthenticated, AdminConfig]

    def list(self, request):
        qs = IndividualException.objects.select_related("user").all()
        kind = request.query_params.get("kind")
        if kind == "temporary":
            qs = qs.filter(duration=IndividualException.DURATION_TEMPORARY)
        data = IndividualExceptionSerializer(qs, many=True).data
        expiry_events = AuditEvent.objects.filter(event_type="access_change", action="exception_removed", actor_type="scheduled")[:10]
        return Response({
            "results": data,
            "expiry_events": [{"id": e.id, "occurred_at": e.occurred_at, "actor_label": e.actor_label, "actor_type": e.actor_type, "summary": e.summary} for e in expiry_events],
        })

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, AdminConfig, IsSystemOwner])
    def end(self, request, pk=None):
        exc = IndividualException.objects.filter(pk=pk).first()
        if exc is None:
            return Response({"code": "not_found", "detail": "Exception not found."}, status=404)
        services.remove_exception(exc, actor_desc=str(request.user), reason=request.data.get("reason", ""))
        return Response(IndividualExceptionSerializer(exc).data)


class SystemOwnerViewSet(BriteViewSet):
    permission_classes = [IsAuthenticated, AdminConfig]

    def list(self, request):
        owners = services.active_system_owners()
        blocked = AuditEvent.objects.filter(action="system_owner_removal_blocked")[:5]
        return Response({
            "results": SystemOwnerSerializer(owners, many=True).data,
            "minimum": services.MINIMUM_SYSTEM_OWNERS,
            "can_manage": is_system_owner(request.user),
            "candidates": UserSummarySerializer(User.objects.filter(is_active=True).exclude(pk__in=owners.values_list("user_id", flat=True)), many=True).data,
            "recent_blocked": [{"id": e.id, "occurred_at": e.occurred_at, "summary": e.summary, "actor_label": e.actor_label} for e in blocked],
        })

    def create(self, request):
        if not is_system_owner(request.user):
            return Response({"code": "forbidden", "detail": "Only a System Owner can assign System Owners."}, status=403)
        user = User.objects.filter(pk=request.data.get("user_id"), is_active=True).first()
        if user is None:
            return Response({"code": "not_found", "detail": "User not found."}, status=404)
        owner = services.add_system_owner(user, assigned_by=str(request.user))
        return Response(SystemOwnerSerializer(owner).data, status=201)

    @action(detail=True, methods=["post"])
    def remove(self, request, pk=None):
        if not is_system_owner(request.user):
            return Response({"code": "forbidden", "detail": "Only a System Owner can remove System Owners."}, status=403)
        owner = services.active_system_owners().filter(pk=pk).first()
        if owner is None:
            return Response({"code": "not_found", "detail": "System Owner not found."}, status=404)
        services.remove_system_owner(owner, removed_by=str(request.user))
        return Response(SystemOwnerSerializer(owner).data)


class WorkspaceGroupViewSet(BriteViewSet):
    permission_classes = [IsAuthenticated, AdminConfig]

    def list(self, request):
        groups = WorkspaceGroupMapping.objects.all()
        matrix = role_defaults_matrix()
        return Response({
            "groups": WorkspaceGroupMappingSerializer(groups, many=True).data,
            "roles": [{"code": r, "label": Role.LABELS[r]} for r in Role.ORDER],
            "capabilities": [{"code": c, "label": Capability.LABELS[c]} for c in Capability.ORDER],
            "defaults": matrix,
            "default_versions": {f"{d.role}:{d.capability}": d.version for d in RoleCapabilityDefault.objects.all()},
            "system_owners": SystemOwnerSerializer(services.active_system_owners(), many=True).data,
            "can_manage": is_system_owner(request.user),
            "directory_sync": services.DirectoryClient.is_configured(),
        })

    def create(self, request):
        if not is_system_owner(request.user):
            return Response({"code": "forbidden", "detail": "Only a System Owner can map Workspace groups."}, status=403)
        serializer = WorkspaceGroupMappingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mapping = create_versioned(
            WorkspaceGroupMapping, event_type="access_change",
            summary=f"Workspace group {serializer.validated_data['group_email']} mapped to role {Role.LABELS[serializer.validated_data['role']]}",
            **serializer.validated_data,
        )
        return Response(WorkspaceGroupMappingSerializer(mapping).data, status=201)

    def partial_update(self, request, pk=None):
        if not is_system_owner(request.user):
            return Response({"code": "forbidden", "detail": "Only a System Owner can map Workspace groups."}, status=403)
        mapping = WorkspaceGroupMapping.objects.filter(pk=pk).first()
        if mapping is None:
            return Response({"code": "not_found", "detail": "Group not found."}, status=404)
        serializer = WorkspaceGroupMappingSerializer(mapping, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = {k: v for k, v in serializer.validated_data.items() if k in {"group_email", "role", "is_active"}}
        save_versioned(
            mapping, changes, expected_version=request.data.get("version"), event_type="access_change",
            summary=f"Workspace group {mapping.group_email} mapping changed",
        )
        return Response(WorkspaceGroupMappingSerializer(mapping).data)

    @action(detail=False, methods=["post"], url_path="defaults")
    def set_default(self, request):
        if not is_system_owner(request.user):
            return Response({"code": "forbidden", "detail": "Only a System Owner can change role defaults."}, status=403)
        role, capability, level = request.data.get("role"), request.data.get("capability"), request.data.get("level")
        if role not in Role.LABELS or capability not in Capability.LABELS or level not in Level.LABELS:
            raise BusinessRuleViolation("Unknown role, capability or level.")
        row, created = RoleCapabilityDefault.objects.get_or_create(role=role, capability=capability, defaults={"level": Level.NONE})
        save_versioned(
            row, {"level": level}, expected_version=request.data.get("version") or row.version, event_type="access_change",
            summary=f"Role default changed · {Role.LABELS[role]} · {Capability.LABELS[capability]}: {Level.LABELS[row.level]} → {Level.LABELS[level]}",
        )
        return Response(RoleCapabilityDefaultSerializer(row).data)
