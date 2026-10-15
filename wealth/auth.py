"""Portfolio access only; Django admin retains its own staff authentication."""

from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required


def portfolio_access_required(view):
    authenticated_view = login_required(view)

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if settings.TALLY_AUTH_ENABLED:
            return authenticated_view(request, *args, **kwargs)
        return view(request, *args, **kwargs)

    return wrapped
