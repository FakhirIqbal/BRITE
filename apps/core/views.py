"""Base view behaviour: attach the per-request DB context after authentication."""
from __future__ import annotations

from rest_framework import viewsets
from rest_framework.views import APIView

from apps.core.context import ActorContext, ActorType, get_actor, set_actor
from apps.core.db import apply_db_context


def bind_request_context(request) -> ActorContext:
    """Build the actor context for an authenticated request and apply it to the DB."""
    from apps.accounts.access import effective_access_detail

    user = getattr(request, "user", None)
    base = get_actor()
    if user is not None and user.is_authenticated:
        # Identity first (so the access tables' own-row policies let us read), then capabilities.
        apply_db_context(ActorContext(user_id=user.pk, actor_type=ActorType.HUMAN, request_id=base.request_id))
        detail = effective_access_detail(user)
        ctx = ActorContext(
            user_id=user.pk,
            actor_type=ActorType.HUMAN,
            actor_label=user.full_name or user.email,
            capabilities=detail["effective"],
            roles=detail["roles"],
            request_id=base.request_id,
            user=user,
            access_detail=detail,
        )
    else:
        ctx = ActorContext(request_id=base.request_id)
    set_actor(ctx)
    apply_db_context(ctx)
    request.actor_context = ctx
    return ctx


class ContextBoundMixin:
    def perform_authentication(self, request):
        super().perform_authentication(request)
        bind_request_context(request)


class BriteAPIView(ContextBoundMixin, APIView):
    pass


class BriteViewSet(ContextBoundMixin, viewsets.GenericViewSet):
    pass
