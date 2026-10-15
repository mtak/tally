from django.contrib import admin
from django.urls import include, path
from .views import PortfolioLoginView, PortfolioLogoutView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("language/", include("django.conf.urls.i18n")),
    path(
        "login/",
        PortfolioLoginView.as_view(),
        name="login",
    ),
    path("logout/", PortfolioLogoutView.as_view(), name="logout"),
    path("", include("wealth.urls")),
]
