"""Portfolio access only; Django admin retains its own staff authentication."""

from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404


def import_history_enabled(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not settings.TALLY_IMPORT_HISTORY_ENABLED:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapped


def portfolio_access_required(view):
    authenticated_view = login_required(view)

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if settings.TALLY_AUTH_ENABLED:
            return authenticated_view(request, *args, **kwargs)
        return view(request, *args, **kwargs)

    return wrapped
