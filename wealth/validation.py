"""Shared financial rules. Values in storage are signed integer cents."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

MIN_MINOR = -(2**63)
MAX_MINOR = 2**63 - 1


def validate_minor(value):
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or not MIN_MINOR <= value <= MAX_MINOR:
        raise ValidationError(_("Enter an integer amount within the supported storage range."))


def to_minor(value):
    if value is None:
        return None
    try:
        value = Decimal(value)
        if not value.is_finite() or not Decimal(MIN_MINOR) / 100 - 1 <= value <= Decimal(MAX_MINOR) / 100 + 1:
            raise InvalidOperation
        with localcontext() as context:
            context.prec = max(30, len(value.as_tuple().digits) + 3)
            result = int((value * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        validate_minor(result)
        return result
    except (InvalidOperation, ValueError, TypeError, OverflowError) as exc:
        raise ValidationError(_("Enter a finite amount within the supported storage range.")) from exc


def validate_balance(kind, asset_class, value):
    if isinstance(value, Decimal) and not value.is_finite():
        return  # The storage validator reports invalid numeric values.
    if value is not None and isinstance(value, (int, Decimal)) and ((kind == 'mortgage' and value > 0) or
                             (kind != 'mortgage' and asset_class != 'credit_card' and value < 0)):
        raise ValidationError(_("Use a negative balance for a mortgage and a nonnegative balance for assets."))


def validate_account(account, owner_kind):
    errors = {}
    if account.joint and (account.kind != 'bank' or
                          owner_kind is not None and owner_kind != 'private'):
        errors['joint'] = _("Only a private bank account can be shared.")
    for end in ('closed_on', 'matures_on'):
        if account.started_on and getattr(account, end) and getattr(account, end) < account.started_on:
            errors[end] = _("This date must be on or after the start date.")
    if errors:
        raise ValidationError(errors)
