from decimal import Decimal, ROUND_HALF_UP
from django import template
from wealth.numbers import format_decimal
from wealth.preferences import show_cents, whole_amount

register = template.Library()


@register.filter
def money(value):
    if value is None:
        return "—"
    amount = Decimal(value) / 100
    digits = 2 if show_cents.get() else 0
    if not digits:
        amount = whole_amount(amount)
    return "€ " + format_decimal(amount, digits)


@register.filter
def percent(value):
    if value is None:
        return "—"
    displayed = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format_decimal(displayed, 2) + "%"
