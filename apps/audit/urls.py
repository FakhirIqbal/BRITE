from django.urls import path

from apps.audit.views import AuditIntegrityView, AuditTimelineView, ClientHistoryView

urlpatterns = [
    path("events/", AuditTimelineView.as_view(), name="audit-events"),
    path("integrity/", AuditIntegrityView.as_view(), name="audit-integrity"),
    path("clients/<int:client_pk>/", ClientHistoryView.as_view(), name="audit-client-history"),
]
