"""
Google Workspace integration for sign-in and group membership.

- verify_id_token(): validates the Google Identity Services credential and
  checks it belongs to BRITE's Workspace domain.
- DirectoryClient: reads a user's group memberships through the Admin SDK
  Directory API using a service account with domain-wide delegation. When
  the service account is not configured the client reports itself as
  unavailable and memberships recorded by administrators are used instead.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

DIRECTORY_SCOPE = "https://www.googleapis.com/auth/admin.directory.group.readonly"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


class GoogleSignInError(Exception):
    pass


@dataclass
class GoogleIdentity:
    sub: str
    email: str
    name: str
    picture: str
    hosted_domain: str


def verify_id_token(credential: str) -> GoogleIdentity:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    if not settings.GOOGLE_CLIENT_ID:
        raise GoogleSignInError("Google sign-in is not configured on the server (GOOGLE_CLIENT_ID).")
    try:
        claims = id_token.verify_oauth2_token(credential, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
    except ValueError as exc:
        raise GoogleSignInError("The Google sign-in token could not be verified.") from exc
    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise GoogleSignInError("Unexpected token issuer.")
    if not claims.get("email_verified"):
        raise GoogleSignInError("The Google account email is not verified.")
    hosted_domain = claims.get("hd", "")
    expected = settings.GOOGLE_WORKSPACE_DOMAIN.lower()
    email = claims.get("email", "").lower()
    if expected and (hosted_domain.lower() != expected or not email.endswith("@" + expected)):
        raise GoogleSignInError("Sign in with your BRITE Google Workspace account.")
    return GoogleIdentity(
        sub=claims["sub"],
        email=email,
        name=claims.get("name", ""),
        picture=claims.get("picture", ""),
        hosted_domain=hosted_domain,
    )


def _service_account_session(scopes: list[str], subject: str | None = None):
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(settings.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
    if subject:
        credentials = credentials.with_subject(subject)
    return AuthorizedSession(credentials)


class DirectoryClient:
    BASE = "https://admin.googleapis.com/admin/directory/v1"

    @staticmethod
    def is_configured() -> bool:
        return bool(settings.GOOGLE_SERVICE_ACCOUNT_FILE and settings.GOOGLE_DIRECTORY_ADMIN_EMAIL)

    def __init__(self):
        self.session = _service_account_session([DIRECTORY_SCOPE], subject=settings.GOOGLE_DIRECTORY_ADMIN_EMAIL)

    def groups_for_user(self, email: str) -> list[str]:
        """Return the group emails the user belongs to (direct and nested)."""
        emails: list[str] = []
        page_token = None
        while True:
            params = {"userKey": email, "maxResults": 200}
            if page_token:
                params["pageToken"] = page_token
            response = self.session.get(f"{self.BASE}/groups", params=params, timeout=20)
            response.raise_for_status()
            data = response.json()
            emails.extend(g["email"].lower() for g in data.get("groups", []) if g.get("email"))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return emails

    def group_member_count(self, group_email: str) -> int:
        response = self.session.get(f"{self.BASE}/groups/{group_email}", params={"fields": "directMembersCount"}, timeout=20)
        response.raise_for_status()
        return int(response.json().get("directMembersCount", 0))
