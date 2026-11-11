"""Configuration screens (first set: status sets)."""
from __future__ import annotations

from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import capability_permission
from apps.accounts.roles import Capability, Level
from apps.configuration.models import StatusOption, StatusSet
from apps.configuration.serializers import StatusOptionSerializer, StatusSetSerializer
from apps.core.exceptions import BusinessRuleViolation
from apps.core.services import create_versioned, save_versioned
from apps.core.views import BriteViewSet


class StatusSetViewSet(BriteViewSet):
    permission_classes = [IsAuthenticated, capability_permission(Capability.ADMINISTRATIVE_CONFIGURATION)]

    def list(self, request):
        return Response(StatusSetSerializer(StatusSet.objects.prefetch_related("options"), many=True).data)

    def retrieve(self, request, pk=None):
        status_set = StatusSet.objects.prefetch_related("options").filter(key=pk).first()
        if status_set is None:
            return Response({"code": "not_found", "detail": "Status set not found."}, status=404)
        return Response(StatusSetSerializer(status_set).data)

    @action(detail=True, methods=["post"], url_path="options")
    def add_option(self, request, pk=None):
        status_set = StatusSet.objects.filter(key=pk).first()
        if status_set is None:
            return Response({"code": "not_found", "detail": "Status set not found."}, status=404)
        serializer = StatusOptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if StatusOption.objects.filter(status_set=status_set, code=data["code"]).exists():
            raise BusinessRuleViolation("A status with that code already exists in this set.")
        data.setdefault("sort_order", (status_set.options.count() or 0) + 1)
        option = create_versioned(
            StatusOption, event_type="configuration", summary=f"Status added · {status_set.name} · {data['label']}",
            status_set=status_set, **data,
        )
        return Response(StatusOptionSerializer(option).data, status=201)

    @action(detail=True, methods=["patch"], url_path=r"options/(?P<option_id>\d+)")
    def update_option(self, request, pk=None, option_id=None):
        option = StatusOption.objects.filter(status_set__key=pk, pk=option_id).select_related("status_set").first()
        if option is None:
            return Response({"code": "not_found", "detail": "Status not found."}, status=404)
        serializer = StatusOptionSerializer(option, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = {k: v for k, v in serializer.validated_data.items() if k in {"label", "tone", "sort_order", "is_active", "is_terminal"}}
        save_versioned(
            option, changes, expected_version=request.data.get("version"), event_type="configuration",
            summary=f"Status changed · {option.status_set.name} · {option.label}",
        )
        return Response(StatusOptionSerializer(option).data)


class PublicStatusSetsView(BriteViewSet):
    """Read-only vocabulary for any signed-in user (used to render chips and pickers)."""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        data = {}
        for status_set in StatusSet.objects.prefetch_related("options"):
            data[status_set.key] = [
                {"code": o.code, "label": o.label, "tone": o.tone, "is_active": o.is_active, "is_terminal": o.is_terminal}
                for o in status_set.options.all()
            ]
        return Response(data)
