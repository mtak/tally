from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("language/", include("django.conf.urls.i18n")),
    path(
        "login/",
        auth.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("", include("wealth.urls")),
]
