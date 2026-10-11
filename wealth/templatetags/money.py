from decimal import Decimal
from django import template
from django.utils.formats import number_format

register = template.Library()


@register.filter
def money(value):
    if value is None:
        return "—"
    return "€ " + number_format(
        Decimal(value) / 100, decimal_pos=2, use_l10n=True, force_grouping=True
    )


@register.filter
def percent(value):
    if value is None:
        return "—"
    return number_format(value, decimal_pos=2, use_l10n=True) + "%"
