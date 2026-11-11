"""
Google Shared Drive connection.

Uses the service account (domain-wide delegation not required for Drive when
the service account itself is a member of the Shared Drive) to create the
base folder structure and permission each folder to the mapped Workspace
groups. Without credentials the integration reports itself as not connected;
nothing is simulated.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import WorkspaceGroupMapping
from apps.audit.services import record_event
from apps.drive.models import BASE_FOLDERS, DriveFolder

logger = logging.getLogger(__name__)
DRIVE_API = "https://www.googleapis.com/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveNotConfigured(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.GOOGLE_SERVICE_ACCOUNT_FILE and settings.GOOGLE_SHARED_DRIVE_ID)


def _session():
    from apps.accounts.google import DRIVE_SCOPE, _service_account_session

    if not is_configured():
        raise DriveNotConfigured("Shared Drive is not connected: set GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_SHARED_DRIVE_ID.")
    return _service_account_session([DRIVE_SCOPE])


def shared_drive_info() -> dict:
    session = _session()
    response = session.get(f"{DRIVE_API}/drives/{settings.GOOGLE_SHARED_DRIVE_ID}", params={"fields": "id,name,createdTime"}, timeout=20)
    response.raise_for_status()
    return response.json()


def find_or_create_folder(session, name: str, parent_id: str) -> dict:
    query = f"name = '{name.replace("'", "\\'")}' and mimeType = '{FOLDER_MIME}' and '{parent_id}' in parents and trashed = false"
    response = session.get(
        f"{DRIVE_API}/files",
        params={"q": query, "corpora": "drive", "driveId": settings.GOOGLE_SHARED_DRIVE_ID, "includeItemsFromAllDrives": "true",
                "supportsAllDrives": "true", "fields": "files(id,name,webViewLink)"},
        timeout=20,
    )
    response.raise_for_status()
    files = response.json().get("files", [])
    if files:
        return files[0]
    response = session.post(
        f"{DRIVE_API}/files", params={"supportsAllDrives": "true", "fields": "id,name,webViewLink"},
        json={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}, timeout=20,
    )
    response.raise_for_status()
    return response.json()


def ensure_group_permission(session, file_id: str, group_email: str, role: str) -> None:
    response = session.get(
        f"{DRIVE_API}/files/{file_id}/permissions",
        params={"supportsAllDrives": "true", "fields": "permissions(id,emailAddress,role,type)"}, timeout=20,
    )
    response.raise_for_status()
    for perm in response.json().get("permissions", []):
        if perm.get("emailAddress", "").lower() == group_email.lower():
            if perm.get("role") != role:
                session.patch(f"{DRIVE_API}/files/{file_id}/permissions/{perm['id']}", params={"supportsAllDrives": "true"}, json={"role": role}, timeout=20).raise_for_status()
            return
    session.post(
        f"{DRIVE_API}/files/{file_id}/permissions",
        params={"supportsAllDrives": "true", "sendNotificationEmail": "false"},
        json={"type": "group", "role": role, "emailAddress": group_email}, timeout=20,
    ).raise_for_status()


def move_folder(session, file_id: str, new_parent_id: str) -> None:
    """Move (never copy) a folder to a new parent, used when a family proceeds."""
    meta = session.get(f"{DRIVE_API}/files/{file_id}", params={"supportsAllDrives": "true", "fields": "parents"}, timeout=20)
    meta.raise_for_status()
    previous = ",".join(meta.json().get("parents", []))
    session.patch(
        f"{DRIVE_API}/files/{file_id}", params={"supportsAllDrives": "true", "addParents": new_parent_id, "removeParents": previous},
        json={}, timeout=20,
    ).raise_for_status()


def _group_emails_by_role() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for mapping in WorkspaceGroupMapping.objects.filter(is_active=True):
        result.setdefault(mapping.role, []).append(mapping.group_email)
    return result


@transaction.atomic(savepoint=False)
def provision_base_folders() -> list[DriveFolder]:
    """Create (or verify) the base folders in the Shared Drive and permission them by group."""
    session = _session()
    drive = shared_drive_info()
    now = timezone.now()
    root, _ = DriveFolder.objects.get_or_create(
        kind=DriveFolder.KIND_ROOT, defaults={"name": drive["name"], "google_file_id": drive["id"], "web_url": f"https://drive.google.com/drive/folders/{drive['id']}"},
    )
    root.name, root.google_file_id, root.last_verified_at, root.last_error = drive["name"], drive["id"], now, ""
    root.save(update_fields=["name", "google_file_id", "last_verified_at", "last_error"])
    groups_by_role = _group_emails_by_role()
    folders = [root]
    for spec in BASE_FOLDERS:
        folder, _ = DriveFolder.objects.get_or_create(kind=spec["kind"], parent=root, defaults={"name": spec["name"]})
        try:
            remote = find_or_create_folder(session, spec["name"], drive["id"])
            applied = []
            for role, drive_role in spec["roles"].items():
                for email in groups_by_role.get(role, []):
                    ensure_group_permission(session, remote["id"], email, drive_role)
                    applied.append({"group_email": email, "role": drive_role, "app_role": role})
            folder.google_file_id = remote["id"]
            folder.web_url = remote.get("webViewLink", f"https://drive.google.com/drive/folders/{remote['id']}")
            folder.permissions = applied
            folder.last_verified_at = now
            folder.last_error = ""
        except Exception as exc:  # keep going; the screen shows per-folder errors
            logger.exception("Drive provisioning failed for %s", spec["name"])
            folder.last_error = str(exc)[:300]
        folder.save()
        folders.append(folder)
    record_event(
        root, event_type="configuration", action="drive_provisioned",
        summary=f"Shared Drive folders created/verified in '{drive['name']}' and permissioned by Workspace group",
    )
    return folders
