from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.rssapp.forms import EmailLoginForm
from apps.rssapp.views import signup_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="auth/login.html",
            authentication_form=EmailLoginForm,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", signup_view, name="signup"),
    path("", include("apps.rssapp.urls")),
    path("api/", include("apps.rssapp.api_urls")),
]
