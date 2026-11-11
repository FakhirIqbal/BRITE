from rest_framework.routers import DefaultRouter

from apps.configuration.views import PublicStatusSetsView, StatusSetViewSet

router = DefaultRouter()
router.register("admin/configuration/status-sets", StatusSetViewSet, basename="admin-status-sets")
router.register("vocabulary", PublicStatusSetsView, basename="vocabulary")

urlpatterns = router.urls
