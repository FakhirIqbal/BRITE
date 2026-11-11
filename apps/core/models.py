"""
Shared abstract models.

VersionedModel provides the concurrent-write protection every editable
record needs: a monotonically increasing version plus who/when last saved.
Writes must go through apps.core.services.save_versioned so a stale version
is refused instead of silently overwriting.
"""
from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class VersionedModel(TimeStampedModel):
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    updated_by_label = models.CharField(max_length=160, blank=True, default="System")

    class Meta:
        abstract = True

    # Subclasses may override to describe the record in audit entries and messages.
    def audit_label(self) -> str:
        return f"{self._meta.verbose_name} #{self.pk}"

    def audit_stream(self) -> str:
        return f"{self._meta.label_lower}:{self.pk}"
