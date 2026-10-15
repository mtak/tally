"""Locale-aware numbers at UI boundaries; internal values remain Decimal/cents."""
import re
from decimal import Decimal

from django import forms
from django.utils.formats import get_format, number_format
from django.utils import numberformat
from django.utils.translation import gettext_lazy as _


def format_decimal(value, decimal_places=None):
    return number_format(
        value, decimal_pos=decimal_places, use_l10n=True, force_grouping=True
    )


class LocalizedNumberInput(forms.TextInput):
    def format_value(self, value):
        # Bound strings must survive validation exactly as entered. Initial values
        # are numeric, and must never pass through the user's input parser.
        if isinstance(value, (Decimal, int, float)):
            return numberformat.format(value, get_format("DECIMAL_SEPARATOR"), grouping=0)
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
            # A single separator is decimal, except a three-digit suffix that
            # could also be thousands grouping. Never guess its magnitude.
            if re.fullmatch(r"[+-]?[0-9]{1,3}[.,][0-9]{3}", value):
                raise forms.ValidationError(
                    _("Ambiguous number. Remove thousands separators, or use two decimal places."),
                    code="ambiguous",
                )
            if re.fullmatch(r"[+-]?[0-9]+(?:[.,][0-9]+)?", value):
                value = Decimal(value.replace(",", "."))
            else:
                # Grouped inputs need either multiple groups or an explicit
                # decimal part with the other separator. Both conventions work.
                for group, decimal in ((",", "."), (".", ",")):
                    grouped = rf"[+-]?[0-9]{{1,3}}(?:{re.escape(group)}[0-9]{{3}})+"
                    fraction = rf"{re.escape(decimal)}[0-9]+"
                    if re.fullmatch(grouped + rf"(?:{fraction})?", value):
                        value = Decimal(value.replace(group, "").replace(decimal, "."))
                        break
                else:
                    raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        return super().to_python(value)
