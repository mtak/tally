"""Locale-aware numbers at UI boundaries; internal values remain Decimal/cents."""
import re
from decimal import Decimal

from django import forms
from django.utils.formats import get_format, number_format


def format_decimal(value, decimal_places=None):
    return number_format(
        value, decimal_pos=decimal_places, use_l10n=True, force_grouping=True
    )


class LocalizedNumberInput(forms.TextInput):
    def format_value(self, value):
        # Bound strings must survive validation exactly as entered. Initial values
        # are numeric, and must never pass through the user's input parser.
        if isinstance(value, (Decimal, int, float)):
            return format_decimal(value)
        return super().format_value(value)


class LocalizedDecimalField(forms.DecimalField):
    widget = LocalizedNumberInput

    def __init__(self, *args, **kwargs):
        kwargs["localize"] = True
        super().__init__(*args, **kwargs)
        self.widget.attrs.setdefault("inputmode", "decimal")

    def to_python(self, value):
        if isinstance(value, str) and value not in self.empty_values:
            value = value.strip()
            decimal = get_format("DECIMAL_SEPARATOR")
            group = get_format("THOUSAND_SEPARATOR")
            # Grouping is optional but, when present, every group has three
            # digits. Reject foreign separators, exponents and partial parses.
            integer = rf"(?:[0-9]+|[0-9]{{1,3}}(?:{re.escape(group)}[0-9]{{3}})+)"
            pattern = rf"[+-]?{integer}(?:{re.escape(decimal)}[0-9]+)?"
            if not re.fullmatch(pattern, value):
                raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
            value = Decimal(value.replace(group, "").replace(decimal, "."))
        return super().to_python(value)
