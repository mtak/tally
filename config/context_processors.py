from django.conf import settings


def instance_name(request):
    return {"tally_instance_name": settings.TALLY_INSTANCE_NAME.strip()}
