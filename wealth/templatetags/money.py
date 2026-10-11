from decimal import Decimal
from django import template
from django.utils.formats import number_format
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
    return "€ " + number_format(
        amount, decimal_pos=digits, use_l10n=True, force_grouping=True
    )


@register.filter
def percent(value):
    if value is None:
        return "—"
    return number_format(value, decimal_pos=2, use_l10n=True) + "%"
