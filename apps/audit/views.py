"""Audit history: administrator timeline plus per-record history."""
from __future__ import annotations

from django.db.models import Q
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import capability_permission
from apps.accounts.roles import Capability, Level
from apps.audit.models import AuditEvent
from apps.audit.serializers import AuditEventSerializer
from apps.audit.services import verify_stream
from apps.core.views import BriteAPIView, ContextBoundMixin


class AuditTimelineView(ContextBoundMixin, ListAPIView):
    """Administrator audit history with the design's filters."""

    serializer_class = AuditEventSerializer
    permission_classes = [IsAuthenticated, capability_permission(Capability.AUDIT_HISTORY)]

    def get_queryset(self):
        qs = AuditEvent.objects.select_related("origin_event").all()
        params = self.request.query_params
        event_type = params.get("event_type")
        if event_type and event_type != "all":
            qs = qs.filter(event_type=event_type)
        actor_type = params.get("actor_type")
        if actor_type and actor_type != "all":
            qs = qs.filter(actor_type=actor_type)
        if params.get("self_granted") in {"1", "true"}:
            qs = qs.filter(flags__contains=["self_granted"])
        search = params.get("q", "").strip()
        if search:
            qs = qs.filter(
                Q(summary__icontains=search)
                | Q(entity_label__icontains=search)
                | Q(actor_label__icontains=search)
                | Q(stream__icontains=search)
            )
        stream = params.get("stream")
        if stream:
            qs = qs.filter(stream=stream)
        return qs


class AuditIntegrityView(BriteAPIView):
    permission_classes = [IsAuthenticated, capability_permission(Capability.AUDIT_HISTORY)]

    def get(self, request):
        streams = AuditEvent.objects.order_by().values_list("stream", flat=True).distinct()
        checked = 0
        broken = []
        for stream in streams:
            result = verify_stream(stream)
            checked += 1
            if not result["intact"]:
                broken.append({"stream": stream, "broken_at": result["broken_at"]})
        return Response({"streams_checked": checked, "intact": not broken, "broken": broken, "events": AuditEvent.objects.count()})


class ClientHistoryView(ContextBoundMixin, ListAPIView):
    """History for one client record: visible to anyone who can view client data."""

    serializer_class = AuditEventSerializer
    permission_classes = [IsAuthenticated, capability_permission(Capability.CLIENT_OPERATIONAL_DATA, view_level=Level.VIEW)]

    def get_queryset(self):
        return AuditEvent.objects.filter(client_id=self.kwargs["client_pk"]).select_related("origin_event")
