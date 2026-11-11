"""
Users, Workspace group mapping, capability defaults, individual exceptions
and System Owners. Roles are never typed on a user: they come from
Workspace group membership (synced from the Directory or recorded by an
administrator) through the WorkspaceGroupMapping.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.accounts.roles import Capability, Level, Role
from apps.core.models import TimeStampedModel, VersionedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, full_name: str = "", **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, full_name=full_name, **extra)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        # Django admin is not used; keep the manager API complete for tooling.
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        user = self.create_user(email, **extra)
        if password:
            user.set_password(password)
            user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=160, blank=True)
    google_sub = models.CharField(max_length=64, blank=True, default="", db_index=True)
    picture_url = models.URLField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    last_sign_in_at = models.DateTimeField(null=True, blank=True)
    last_group_sync_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ["full_name", "email"]

    def __str__(self) -> str:
        return self.full_name or self.email

    @property
    def initials(self) -> str:
        parts = [p for p in (self.full_name or self.email.split("@")[0]).replace(".", " ").split() if p]
        return "".join(p[0] for p in parts[:2]).upper()

    @property
    def first_name(self) -> str:
        return (self.full_name or "").split(" ")[0] if self.full_name else self.email.split("@")[0]

    def audit_label(self) -> str:
        return f"User {self}"

    def audit_stream(self) -> str:
        return f"accounts.user:{self.pk}"


class WorkspaceGroupMapping(VersionedModel):
    """A Workspace group email mapped to one application role."""

    group_email = models.EmailField(unique=True)
    role = models.CharField(max_length=40, choices=Role.CHOICES)
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["group_email"]

    def __str__(self) -> str:
        return f"{self.group_email} → {Role.LABELS.get(self.role, self.role)}"

    def audit_label(self) -> str:
        return f"Workspace group {self.group_email}"

    @property
    def member_count(self) -> int:
        return self.memberships.filter(removed_at__isnull=True).count()


class WorkspaceGroupMembership(TimeStampedModel):
    """
    A user's membership of a mapped Workspace group. Source is 'directory'
    when synced from Google, 'manual' when recorded by an administrator
    (for environments without Directory API access).
    """

    SOURCE_DIRECTORY = "directory"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [(SOURCE_DIRECTORY, "Directory sync"), (SOURCE_MANUAL, "Recorded by administrator")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="group_memberships")
    group = models.ForeignKey(WorkspaceGroupMapping, on_delete=models.CASCADE, related_name="memberships")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    synced_at = models.DateTimeField(default=timezone.now)
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "group"], condition=models.Q(removed_at__isnull=True), name="uniq_active_membership"
            )
        ]

    @property
    def is_active(self) -> bool:
        return self.removed_at is None


class RoleCapabilityDefault(VersionedModel):
    """Default access level a role grants for a capability group."""

    role = models.CharField(max_length=40, choices=Role.CHOICES)
    capability = models.CharField(max_length=40, choices=Capability.CHOICES)
    level = models.CharField(max_length=8, choices=Level.CHOICES, default=Level.NONE)

    class Meta:
        unique_together = [("role", "capability")]
        ordering = ["role", "capability"]

    def audit_label(self) -> str:
        return f"Role default {Role.LABELS.get(self.role)} · {Capability.LABELS.get(self.capability)}"

    def audit_stream(self) -> str:
        return "accounts.roledefaults"


class IndividualException(VersionedModel):
    """
    A per-person change to effective access. A grant raises the level for a
    capability; a removal sets it to None and outlasts later role changes.
    Temporary grants expire and are removed by a scheduled job.
    """

    KIND_GRANT = "grant"
    KIND_REMOVE = "remove"
    KIND_CHOICES = [(KIND_GRANT, "Grant access"), (KIND_REMOVE, "Remove access")]

    DURATION_PERMANENT = "permanent"
    DURATION_TEMPORARY = "temporary"
    DURATION_CHOICES = [(DURATION_PERMANENT, "Permanent"), (DURATION_TEMPORARY, "Temporary")]

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="access_exceptions")
    capability = models.CharField(max_length=40, choices=Capability.CHOICES)
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    level = models.CharField(max_length=8, choices=Level.CHOICES, default=Level.VIEW)
    reason = models.TextField()
    duration = models.CharField(max_length=10, choices=DURATION_CHOICES, default=DURATION_PERMANENT)
    expires_on = models.DateField(null=True, blank=True)
    granted_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    granted_by_label = models.CharField(max_length=160, blank=True, default="")
    is_self_granted = models.BooleanField(default=False)
    notified_owner_emails = models.JSONField(default=list, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_reason = models.CharField(max_length=200, blank=True, default="")
    removed_by_label = models.CharField(max_length=160, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} · {self.get_kind_display()} · {Capability.LABELS.get(self.capability)}"

    def audit_label(self) -> str:
        return f"Access exception for {self.user}"

    def audit_stream(self) -> str:
        return f"accounts.user:{self.user_id}"

    @property
    def is_expired(self) -> bool:
        return (
            self.duration == self.DURATION_TEMPORARY
            and self.expires_on is not None
            and self.expires_on < timezone.localdate()
        )

    @property
    def is_active(self) -> bool:
        return self.removed_at is None and not self.is_expired

    @property
    def state(self) -> str:
        if self.removed_at:
            return "removed"
        if self.is_expired:
            return "expired"
        return "active"


class SystemOwner(TimeStampedModel):
    """
    System Owner is system access, not content access: owners manage other
    owners, group mapping and exceptions. BRITE keeps at least two at all times.
    """

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="system_owner_records")
    assigned_by_label = models.CharField(max_length=160, blank=True, default="Sprint 0")
    assigned_at = models.DateTimeField(default=timezone.now)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by_label = models.CharField(max_length=160, blank=True, default="")

    class Meta:
        ordering = ["assigned_at"]
        constraints = [
            models.UniqueConstraint(fields=["user"], condition=models.Q(removed_at__isnull=True), name="uniq_active_system_owner")
        ]

    @property
    def is_active(self) -> bool:
        return self.removed_at is None

    def audit_label(self) -> str:
        return f"System Owner {self.user}"

    def audit_stream(self) -> str:
        return f"accounts.user:{self.user_id}"
