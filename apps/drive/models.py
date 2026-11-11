"""Folders BRITE's application manages inside the BRITE Shared Drive, and who they are permissioned to."""
from django.db import models

from apps.core.models import VersionedModel


class DriveFolder(VersionedModel):
    KIND_ROOT = "root"
    KIND_POTENTIAL_CLIENTS = "potential_clients"
    KIND_CLIENTS = "clients"
    KIND_STAFF = "staff"
    KIND_CLIENT = "client"
    KIND_CHOICES = [
        (KIND_ROOT, "BRITE Operations root"), (KIND_POTENTIAL_CLIENTS, "Potential Clients"), (KIND_CLIENTS, "Clients"),
        (KIND_STAFF, "Staff"), (KIND_CLIENT, "Client folder"),
    ]

    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    name = models.CharField(max_length=200)
    google_file_id = models.CharField(max_length=120, blank=True, default="")
    web_url = models.URLField(blank=True, default="")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    client = models.ForeignKey("clients.Client", null=True, blank=True, on_delete=models.PROTECT, related_name="drive_folders")
    # [{"group_email": ..., "role": "reader|writer|fileOrganizer"}]
    permissions = models.JSONField(default=list, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name

    def audit_label(self) -> str:
        return f"Drive folder {self.name}"

    def audit_stream(self) -> str:
        return f"drive.folder:{self.pk}"


# Base folder structure created inside the Shared Drive and the Workspace groups
# permissioned on each. Roles map to the configured group emails at run time.
BASE_FOLDERS = [
    {"kind": DriveFolder.KIND_POTENTIAL_CLIENTS, "name": "Potential Clients", "roles": {"client_coordinator": "fileOrganizer", "billing": "writer", "operations": "reader", "administrator": "fileOrganizer"}},
    {"kind": DriveFolder.KIND_CLIENTS, "name": "Clients", "roles": {"client_coordinator": "fileOrganizer", "billing": "writer", "clinical": "writer", "clinical_director": "writer", "hr_staffing": "reader", "operations": "reader", "administrator": "fileOrganizer"}},
    {"kind": DriveFolder.KIND_STAFF, "name": "Staff", "roles": {"hr_staffing": "fileOrganizer", "credentialing": "writer", "administrator": "fileOrganizer"}},
]
