from django.conf import settings
from django.contrib.auth import views as auth
from django.shortcuts import redirect


class PortfolioLoginView(auth.LoginView):
    template_name = "registration/login.html"

    def dispatch(self, request, *args, **kwargs):
        if not settings.TALLY_AUTH_ENABLED:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)


class PortfolioLogoutView(auth.LogoutView):
    def post(self, request, *args, **kwargs):
        if not settings.TALLY_AUTH_ENABLED:
            # Do not end a separate admin session or imply upstream sign-out.
            return redirect("dashboard")
        return super().post(request, *args, **kwargs)
