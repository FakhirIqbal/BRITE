from __future__ import annotations

from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import capability_permission
from apps.accounts.roles import Capability
from apps.drive import services
from apps.drive.models import BASE_FOLDERS, DriveFolder
from apps.core.views import BriteAPIView


def _payload(error: str | None = None) -> dict:
    folders = DriveFolder.objects.exclude(kind=DriveFolder.KIND_CLIENT).select_related("parent")
    return {
        "configured": services.is_configured(),
        "shared_drive_id": settings.GOOGLE_SHARED_DRIVE_ID,
        "service_account_set": bool(settings.GOOGLE_SERVICE_ACCOUNT_FILE),
        "folders": [
            {"id": f.id, "kind": f.kind, "name": f.name, "web_url": f.web_url, "google_file_id": f.google_file_id,
             "permissions": f.permissions, "last_verified_at": f.last_verified_at, "last_error": f.last_error}
            for f in folders
        ],
        "plan": [{"kind": s["kind"], "name": s["name"], "roles": s["roles"]} for s in BASE_FOLDERS],
        "error": error,
    }


class SharedDriveView(BriteAPIView):
    permission_classes = [IsAuthenticated, capability_permission(Capability.ADMINISTRATIVE_CONFIGURATION)]

    def get(self, request):
        return Response(_payload())

    def post(self, request):
        """Create or verify the base folders and their group permissions."""
        try:
            services.provision_base_folders()
        except services.DriveNotConfigured as exc:
            return Response(_payload(str(exc)), status=400)
        except Exception as exc:  # surfaced on screen, never swallowed
            return Response(_payload(f"Google Drive returned an error: {str(exc)[:200]}"), status=502)
        return Response(_payload())
