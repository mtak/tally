from decimal import Decimal
from django import template
from wealth.numbers import format_decimal
from wealth.preferences import show_cents, whole_amount

register = template.Library()


@register.filter
def money(value, force_cents=False):
    if value is None:
        return "—"
    amount = Decimal(value) / 100
    digits = 2 if force_cents or show_cents.get() else 0
    if not digits:
        amount = whole_amount(amount)
    return "€ " + format_decimal(amount, digits)


@register.filter
def percent(value):
    if value is None:
        return "—"
    return format_decimal(value, 2) + "%"
