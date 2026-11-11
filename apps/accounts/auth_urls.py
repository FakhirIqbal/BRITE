from django.urls import path

from apps.accounts.auth_views import AuthConfigView, DevSignInView, GoogleSignInView, MeView, SignOutView

urlpatterns = [
    path("config/", AuthConfigView.as_view(), name="auth-config"),
    path("google/", GoogleSignInView.as_view(), name="auth-google"),
    path("dev-login/", DevSignInView.as_view(), name="auth-dev-login"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("logout/", SignOutView.as_view(), name="auth-logout"),
]
