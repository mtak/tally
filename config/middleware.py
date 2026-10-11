from django.conf import settings
from django.utils import translation
from django.utils.cache import patch_vary_headers
from django.utils.deprecation import MiddlewareMixin


class PreferenceLocaleMiddleware(MiddlewareMixin):
    """Use an explicit language cookie or the app default, ignoring browser locale."""

    def process_request(self, request):
        language = settings.LANGUAGE_CODE
        saved = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        if saved:
            try:
                language = translation.get_supported_language_variant(saved)
            except LookupError:
                pass
        translation.activate(language)
        request.LANGUAGE_CODE = translation.get_language()

    def process_response(self, request, response):
        patch_vary_headers(response, ("Cookie",))
        response.headers.setdefault("Content-Language", request.LANGUAGE_CODE)
        return response
