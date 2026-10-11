from contextvars import ContextVar
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings

show_cents = ContextVar("show_cents", default=False)


def cents_cookie_name():
    return settings.SESSION_COOKIE_NAME + "_show_cents"


def whole_amount(value):
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


class MoneyPreferenceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.show_cents = request.COOKIES.get(cents_cookie_name()) == "1"
        token = show_cents.set(request.show_cents)
        try:
            return self.get_response(request)
        finally:
            show_cents.reset(token)
