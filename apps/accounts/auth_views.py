"""Sign-in (Workspace SSO), session info and sign-out."""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import login, logout
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services
from apps.accounts.access import effective_capabilities, is_system_owner, navigation_for, user_roles
from apps.accounts.google import DirectoryClient, GoogleSignInError, verify_id_token
from apps.accounts.models import User
from apps.accounts.roles import Capability, Role
from apps.audit.services import record_event
from apps.core.context import ActorContext, ActorType, actor_scope, system_actor
from apps.core.views import BriteAPIView, bind_request_context


def _finish_sign_in(request, user: User, method: str) -> Response:
    with system_actor("Workspace sign-in"):
        services.record_sign_in(user)
        synced = services.sync_from_directory(user)
        login(request, user)
    bind_request_context(request)
    with actor_scope(ActorContext(user_id=user.pk, actor_type=ActorType.HUMAN, actor_label=str(user), request_id=getattr(request, "request_id", ""))):
        record_event(
            event_type="sign_in", action="signed_in",
            summary=f"{user} signed in via {method}" + (f" · groups synced ({len(synced['added'])} added, {len(synced['removed'])} removed)" if synced else ""),
            stream=user.audit_stream(), entity_type="accounts.user", entity_id=str(user.pk), entity_label=str(user), subject_user_id=user.pk,
        )
    return Response(session_payload(request, user))


def session_payload(request, user: User) -> dict:
    ctx = getattr(request, "actor_context", None)
    if ctx is not None and ctx.user_id == user.pk and ctx.access_detail:
        caps, roles = ctx.capabilities, ctx.roles
    else:
        caps = effective_capabilities(user)
        roles = user_roles(user)
    return {
        "user": {
            "id": user.pk, "email": user.email, "full_name": user.full_name, "first_name": user.first_name,
            "initials": user.initials, "picture_url": user.picture_url, "last_sign_in_at": user.last_sign_in_at,
        },
        "roles": [{"code": r, "label": Role.LABELS[r]} for r in roles],
        "capabilities": caps,
        "capability_labels": Capability.LABELS,
        "is_system_owner": is_system_owner(user),
        "navigation": navigation_for(user, caps, roles=roles),
        "directory_sync": DirectoryClient.is_configured(),
        "csrf_token": get_token(request),
    }


class AuthConfigView(APIView):
    """Public: what the sign-in page needs."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        get_token(request)  # ensure the CSRF cookie is set for the SPA
        payload = {
            "google_client_id": settings.GOOGLE_CLIENT_ID,
            "workspace_domain": settings.GOOGLE_WORKSPACE_DOMAIN,
            "google_configured": bool(settings.GOOGLE_CLIENT_ID),
            "dev_auth_enabled": settings.DEV_AUTH_ENABLED,
        }
        if settings.DEV_AUTH_ENABLED:
            from django.db import transaction

            with transaction.atomic(), system_actor("Development sign-in"):
                payload["dev_accounts"] = [
                    {"email": u.email, "full_name": u.full_name, "roles": [Role.LABELS[r] for r in user_roles(u)]}
                    for u in User.objects.filter(is_active=True).order_by("full_name")
                ]
        return Response(payload)


class GoogleSignInView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        credential = request.data.get("credential")
        if not credential:
            return Response({"code": "missing_credential", "detail": "Missing Google credential."}, status=400)
        try:
            identity = verify_id_token(credential)
            with system_actor("Workspace sign-in"):
                user = services.user_from_google_identity(identity)
        except GoogleSignInError as exc:
            return Response({"code": "sign_in_failed", "detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)
        except PermissionError as exc:
            return Response({"code": "deactivated", "detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return _finish_sign_in(request, user, "Google Workspace")


class DevSignInView(APIView):
    """Development only: sign in as a seeded fictional account. Disabled unless DEV_AUTH_ENABLED."""

    permission_classes = [AllowAny]

    def post(self, request):
        if not settings.DEV_AUTH_ENABLED:
            return Response({"code": "disabled", "detail": "Development sign-in is disabled."}, status=404)
        email = (request.data.get("email") or "").strip().lower()
        with system_actor("Development sign-in"):
            user = User.objects.filter(email=email, is_active=True).first()
        if user is None:
            return Response({"code": "unknown_account", "detail": "No active account with that email."}, status=400)
        return _finish_sign_in(request, user, "development sign-in")


class MeView(BriteAPIView):
    def get(self, request):
        return Response(session_payload(request, request.user))


class SignOutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response({"detail": "Signed out."})
