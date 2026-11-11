from django.urls import path

from apps.core.health import HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
]
