from contextvars import ContextVar
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings

show_cents = ContextVar("show_cents", default=False)


def whole_amount(value):
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


class MoneyPrecisionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.show_cents = settings.TALLY_MONEY_PRECISION == "cents"
        token = show_cents.set(request.show_cents)
        try:
            return self.get_response(request)
        finally:
            show_cents.reset(token)
