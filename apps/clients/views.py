"""Client record API: list/search, create, detail, workstreams, episodes."""
from __future__ import annotations

from django.db.models import Count, Prefetch, Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import capability_permission
from apps.accounts.roles import Capability
from apps.clients import services
from apps.clients.models import Client, ServiceEpisode, Workstream
from apps.clients.serializers import (
    ClientCreateSerializer, ClientDetailSerializer, ClientListSerializer, ClientUpdateSerializer, ServiceEpisodeSerializer,
    WorkstreamSerializer, WorkstreamUpdateSerializer,
)
from apps.core.exceptions import BusinessRuleViolation
from apps.core.pagination import StandardPagination
from apps.core.views import BriteViewSet

ClientData = capability_permission(Capability.CLIENT_OPERATIONAL_DATA)


def _base_queryset():
    return Client.objects.prefetch_related(
        Prefetch("episodes", queryset=ServiceEpisode.objects.prefetch_related(Prefetch("workstreams", queryset=Workstream.objects.select_related("owner"))))
    )


class ClientViewSet(BriteViewSet):
    permission_classes = [IsAuthenticated, ClientData]
    pagination_class = StandardPagination

    def list(self, request):
        qs = _base_queryset()
        q = request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(Q(code_name__icontains=q) | Q(client_id__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
        state = request.query_params.get("state", "all")
        rows = list(qs.order_by("-updated_at"))
        if state and state != "all":
            rows = [c for c in rows if c.record_state == state]
        page = self.paginate_queryset(rows)
        return self.get_paginated_response(ClientListSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        client = _base_queryset().filter(pk=pk).first()
        if client is None:
            return Response({"code": "not_found", "detail": "Client not found."}, status=404)
        return Response(ClientDetailSerializer(client).data)

    def create(self, request):
        serializer = ClientCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        duplicates = list(services.possible_duplicates(data["first_name"], data["last_name"]))
        if duplicates and not data.get("acknowledge_duplicates"):
            return Response(
                {"code": "possible_duplicates", "detail": "We found records that may be the same client. Nothing is merged automatically.",
                 "duplicates": ClientListSerializer(duplicates, many=True).data},
                status=status.HTTP_409_CONFLICT,
            )
        data.pop("acknowledge_duplicates", None)
        client = services.create_client(**data)
        return Response(ClientDetailSerializer(_base_queryset().get(pk=client.pk)).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        client = Client.objects.filter(pk=pk).first()
        if client is None:
            return Response({"code": "not_found", "detail": "Client not found."}, status=404)
        serializer = ClientUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        version, reason = data.pop("version"), data.pop("reason", "")
        services.update_client(client, data, expected_version=version, reason=reason)
        return Response(ClientDetailSerializer(_base_queryset().get(pk=client.pk)).data)

    @action(detail=False, methods=["get"])
    def duplicates(self, request):
        first, last = request.query_params.get("first_name", ""), request.query_params.get("last_name", "")
        if not last.strip():
            return Response({"results": []})
        return Response({"results": ClientListSerializer(services.possible_duplicates(first, last), many=True).data})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Counts for role home views (real data only)."""
        clients = list(_base_queryset())
        states = {"potential": 0, "active": 0, "closed": 0, "archived": 0}
        for c in clients:
            states[c.record_state] = states.get(c.record_state, 0) + 1
        open_ws = Workstream.objects.filter(episode__state=ServiceEpisode.STATE_OPEN)
        unassigned = open_ws.filter(owner__isnull=True).values("kind").annotate(n=Count("id"))
        mine = open_ws.filter(owner_id=request.user.pk).select_related("episode__client").order_by("due_date", "-updated_at")[:10]
        return Response({
            "clients_total": len(clients),
            "by_state": states,
            "open_episodes": ServiceEpisode.objects.filter(state=ServiceEpisode.STATE_OPEN).count(),
            "unassigned_workstreams": {row["kind"]: row["n"] for row in unassigned},
            "unassigned_total": sum(row["n"] for row in unassigned),
            "my_workstreams": [
                {"id": w.id, "kind": w.kind, "kind_label": Workstream.KIND_LABELS[w.kind], "status": w.status, "next_action": w.next_action,
                 "due_date": w.due_date, "waiting_on": w.waiting_on, "blocker": w.blocker, "client": {"id": w.episode.client_id, "code_name": w.episode.client.code_name, "client_id": w.episode.client.client_id}}
                for w in mine
            ],
            "recent": ClientListSerializer(sorted(clients, key=lambda c: c.updated_at, reverse=True)[:6], many=True).data,
        })

    @action(detail=False, methods=["get"])
    def owners(self, request):
        """People who can own a workstream (active users)."""
        return Response([{"id": u.id, "full_name": u.full_name or u.email, "email": u.email} for u in User.objects.filter(is_active=True)])

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        client = Client.objects.filter(pk=pk).first()
        if client is None:
            return Response({"code": "not_found", "detail": "Client not found."}, status=404)
        services.reactivate(client)
        return Response(ClientDetailSerializer(_base_queryset().get(pk=client.pk)).data, status=201)


class WorkstreamViewSet(BriteViewSet):
    permission_classes = [IsAuthenticated, ClientData]

    def partial_update(self, request, pk=None):
        ws = Workstream.objects.select_related("episode__client", "owner").filter(pk=pk).first()
        if ws is None:
            return Response({"code": "not_found", "detail": "Workstream not found."}, status=404)
        serializer = WorkstreamUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        version, reason = data.pop("version"), data.pop("reason", "")
        if "owner_id" in data:
            owner_id = data.pop("owner_id")
            if owner_id is not None and not User.objects.filter(pk=owner_id, is_active=True).exists():
                raise BusinessRuleViolation("Owner must be an active user.")
            data["owner"] = User.objects.filter(pk=owner_id).first() if owner_id else None
        services.update_workstream(ws, data, expected_version=version, reason=reason)
        return Response(WorkstreamSerializer(ws).data)

    @action(detail=False, methods=["get"])
    def unassigned(self, request):
        rows = (
            Workstream.objects.filter(episode__state=ServiceEpisode.STATE_OPEN, owner__isnull=True)
            .select_related("episode__client").order_by("created_at")
        )
        return Response([
            {"id": w.id, "kind": w.kind, "kind_label": Workstream.KIND_LABELS[w.kind], "monitor_role": Workstream.KIND_MONITOR_ROLE[w.kind],
             "since": w.created_at, "status": w.status, "client": {"id": w.episode.client_id, "code_name": w.episode.client.code_name, "client_id": w.episode.client.client_id, "lifecycle": w.episode.lifecycle}}
            for w in rows
        ])


class EpisodeViewSet(BriteViewSet):
    permission_classes = [IsAuthenticated, ClientData]

    def _get(self, pk):
        return ServiceEpisode.objects.select_related("client").filter(pk=pk).first()

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        episode = self._get(pk)
        if episode is None:
            return Response({"code": "not_found", "detail": "Episode not found."}, status=404)
        services.close_episode(
            episode, reason_code=request.data.get("closure_reason", ""), note=request.data.get("closure_note", ""),
            expected_version=request.data.get("version"),
        )
        return Response(ServiceEpisodeSerializer(episode).data)

    @action(detail=True, methods=["post"])
    def lifecycle(self, request, pk=None):
        episode = self._get(pk)
        if episode is None:
            return Response({"code": "not_found", "detail": "Episode not found."}, status=404)
        services.set_lifecycle(episode, request.data.get("lifecycle", ""), expected_version=request.data.get("version"))
        return Response(ServiceEpisodeSerializer(episode).data)
