from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.accounts.admin_views import AdminOverviewView, ExceptionViewSet, SystemOwnerViewSet, UsersAccessViewSet, WorkspaceGroupViewSet

router = DefaultRouter()
router.register("users", UsersAccessViewSet, basename="admin-users")
router.register("exceptions", ExceptionViewSet, basename="admin-exceptions")
router.register("system-owners", SystemOwnerViewSet, basename="admin-system-owners")
router.register("workspace-groups", WorkspaceGroupViewSet, basename="admin-workspace-groups")

urlpatterns = [
    path("overview/", AdminOverviewView.as_view(), name="admin-overview"),
    *router.urls,
]
