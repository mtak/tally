from django.conf import settings


def instance_name(request):
    return {"tally_instance_name": settings.TALLY_INSTANCE_NAME.strip()}


def authentication(request):
    return {"tally_auth_enabled": settings.TALLY_AUTH_ENABLED}


def release(request):
    commit = settings.TALLY_GIT_COMMIT.strip()
    return {"tally_git_commit": commit, "tally_git_commit_short": commit[:7]}
