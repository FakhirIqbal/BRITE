from rest_framework.routers import DefaultRouter

from apps.clients.views import ClientViewSet, EpisodeViewSet, WorkstreamViewSet

router = DefaultRouter()
router.register("workstreams", WorkstreamViewSet, basename="workstreams")
router.register("episodes", EpisodeViewSet, basename="episodes")
router.register("", ClientViewSet, basename="clients")

urlpatterns = router.urls
