"""Attach a request id and reset the actor context for each request."""
from __future__ import annotations

import uuid

from apps.core.context import ActorContext, reset_actor, set_actor


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4().hex[:12]
        token = set_actor(ActorContext(request_id=request.request_id))
        try:
            response = self.get_response(request)
        finally:
            reset_actor(token)
        response["X-Request-Id"] = request.request_id
        return response
