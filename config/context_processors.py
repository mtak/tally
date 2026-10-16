from django.conf import settings
from wealth.models import Snapshot
from wealth.services import maturity_calendar


def instance_name(request):
    return {"tally_instance_name": settings.TALLY_INSTANCE_NAME.strip()}


def authentication(request):
    return {"tally_auth_enabled": settings.TALLY_AUTH_ENABLED}


def release(request):
    commit = settings.TALLY_GIT_COMMIT.strip()
    return {"tally_git_commit": commit, "tally_git_commit_short": commit[:7]}


def maturity_navigation(request):
    """Show the calendar link only when the selected published date has scheduled claims."""
    if settings.TALLY_AUTH_ENABLED and not request.user.is_authenticated:
        return {"has_scheduled_maturities": False}

    if not hasattr(request, "_maturity_calendar"):
        snapshots = list(Snapshot.objects.filter(complete=True).order_by("date", "pk"))
        selected = next(
            (snapshot for snapshot in snapshots if str(snapshot.pk) == request.GET.get("at")),
            snapshots[-1] if snapshots else None,
        )
        request._maturity_calendar = maturity_calendar(selected) if selected else None

    calendar = request._maturity_calendar
    return {"has_scheduled_maturities": bool(calendar and calendar["quarters"])}
