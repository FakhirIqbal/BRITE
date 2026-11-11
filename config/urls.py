"""Root URL configuration. Every API route lives under /api/."""
from django.urls import include, path

urlpatterns = [
    path("api/auth/", include("apps.accounts.auth_urls")),
    path("api/admin/", include("apps.accounts.admin_urls")),
    path("api/", include("apps.configuration.urls")),
    path("api/admin/", include("apps.drive.urls")),
    path("api/audit/", include("apps.audit.urls")),
    path("api/clients/", include("apps.clients.urls")),
    path("api/", include("apps.core.urls")),
]
