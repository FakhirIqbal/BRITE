"""API error shapes, including the concurrent-write conflict (HTTP 409)."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class ConcurrencyConflict(APIException):
    """Raised when a save targets a record version that is no longer current."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "concurrent_write"

    def __init__(self, *, changed_by: str, changed_at, current_version: int, record_label: str = "This record"):
        self.changed_by = changed_by
        self.changed_at = changed_at
        self.current_version = current_version
        self.record_label = record_label
        when = changed_at.strftime("%b %-d, %Y at %-I:%M %p") if changed_at else "just now"
        detail = (
            f"{record_label} was changed by {changed_by} on {when}. "
            "Your save was not applied. Reload to see the latest version, then reapply your change."
        )
        super().__init__(detail=detail)

    def payload(self) -> dict:
        return {
            "code": self.default_code,
            "detail": str(self.detail),
            "changed_by": self.changed_by,
            "changed_at": self.changed_at.isoformat() if self.changed_at else None,
            "current_version": self.current_version,
        }


class ReadOnlyRecord(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "read_only"
    default_detail = "This record is closed and read-only for active work."


class BusinessRuleViolation(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "business_rule"


def exception_handler(exc, context):
    if isinstance(exc, ConcurrencyConflict):
        return Response(exc.payload(), status=exc.status_code)
    if isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, "message_dict") else {"non_field_errors": exc.messages}
        return Response({"code": "validation", "detail": detail}, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, IntegrityError):
        return Response(
            {"code": "integrity", "detail": "The change conflicts with a database rule and was not saved."},
            status=status.HTTP_409_CONFLICT,
        )
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, (PermissionDenied, Http404)):
        return response
    data = response.data
    if isinstance(data, dict) and "code" not in data:
        code = getattr(exc, "default_code", "error")
        if "detail" in data and len(data) == 1:
            response.data = {"code": code, "detail": data["detail"]}
        else:
            response.data = {"code": "validation", "detail": data}
    return response
