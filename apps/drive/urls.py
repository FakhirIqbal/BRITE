from django.urls import path

from apps.drive.views import SharedDriveView

urlpatterns = [path("shared-drive/", SharedDriveView.as_view(), name="admin-shared-drive")]
