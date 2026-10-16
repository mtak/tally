from decimal import Decimal
from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Account, Entity, Snapshot, ASSETS
from .preferences import whole_amount
from .numbers import LocalizedDecimalField
from .widgets import EuropeanDateInput
from .validation import to_minor


class MoneyField(LocalizedDecimalField):
    whole_only = False
    original = None

    def clean(self, value):
        result = super().clean(value)
        if self.whole_only and result is not None:
            if result != whole_amount(result):
                raise forms.ValidationError(_("Enter a whole amount, or enable cents."))
            if self.original is not None and result == whole_amount(self.original):
                return Decimal(self.original)
        return result


class MoneyFormMixin:
    def __init__(self, *args, show_cents=False, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field, MoneyField) and not show_cents:
                field.whole_only = True
                field.original = self.initial.get(name, field.initial)
                if field.original is not None:
                    self.initial[name] = whole_amount(field.original)
                field.widget.attrs["inputmode"] = "numeric"


def money_field(label, required=False, minimum=None):
    return MoneyField(
        label=label,
        required=required,
        max_digits=16,
        decimal_places=2,
        min_value=minimum,
        localize=True,
        widget=LocalizedDecimalField.widget(attrs={"inputmode": "decimal", "autocomplete": "off"}),
    )


def minor(value):
    return to_minor(value)


class EntityForm(forms.ModelForm):
    class Meta:
        model = Entity
        fields = ["name", "kind", "parent"]


class AccountForm(forms.ModelForm):
    interest_rate = LocalizedDecimalField(
        label=_("Annual interest (%)"),
        required=False,
        min_value=0,
        max_value=100,
        decimal_places=2,
        localize=True,
    )

    class Meta:
        model = Account
        fields = [
            "name",
            "entity",
            "kind",
            "asset_class",
            "liquid",
            "pension",
            "joint",
            "currency",
            "started_on",
            "matures_on",
            "closed_on",
            "notes",
        ]
        help_texts = {
            "asset_class": _("For Credit card, use Bank account as the account type and Liquid availability. Enter outstanding debt as a negative balance, zero when settled, and a positive balance only for money owed to you by the card provider."),
        }
        widgets = {
            k: EuropeanDateInput()
            for k in ["started_on", "matures_on", "closed_on"]
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("started_on", "matures_on", "closed_on"):
            self.fields[name].input_formats = ["%d-%m-%Y"]
            self.fields[name].help_text = _("Use dd-mm-yyyy, for example 05-04-2026.")
        if self.instance.pk:
            self.fields["interest_rate"].initial = Decimal(self.instance.rate_bps) / 100

    def clean_currency(self):
        v = self.cleaned_data["currency"].upper()
        if len(v) != 3 or not v.isalpha():
            raise forms.ValidationError(_("Use a three-letter currency code."))
        return v

    def save(self, commit=True):
        obj = super().save(False)
        obj.rate_bps = int((self.cleaned_data.get("interest_rate") or 0) * 100)
        if commit:
            obj.save()
        return obj


class SnapshotForm(forms.ModelForm):
    ab_rate = LocalizedDecimalField(
        label=_("AB assumption (%)"),
        initial=Decimal("26.90"),
        min_value=0,
        max_value=100,
        decimal_places=2,
        localize=True,
    )
    vpb_rate = LocalizedDecimalField(
        label=_("VPB assumption (%)"),
        initial=Decimal("19.00"),
        min_value=0,
        max_value=100,
        decimal_places=2,
        localize=True,
    )

    class Meta:
        model = Snapshot
        fields = ["date", "notes"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def save(self, commit=True):
        obj = super().save(False)
        obj.ab_bps = int(self.cleaned_data["ab_rate"] * 100)
        obj.vpb_bps = int(self.cleaned_data["vpb_rate"] * 100)
        if commit:
            obj.save()
        return obj


class ValuationForm(MoneyFormMixin, forms.Form):
    account_id = forms.IntegerField(widget=forms.HiddenInput)
    amount = money_field(_("Value (EUR)"))
    net_deposits = money_field(_("Net deposits since opening (EUR)"))
    basis = money_field(_("Tax basis (EUR)"))
    interest = money_field(_("Interest received or accrued (EUR)"))

    def clean(self):
        data = super().clean()
        if data.get("amount") is None and any(
            data.get(key) is not None for key in ("net_deposits", "basis", "interest")
        ):
            raise forms.ValidationError(
                _("Enter an account value before entering net deposits, interest or tax basis.")
            )
        return data


class ImportForm(forms.Form):
    file = forms.FileField(label=_("Overview CSV"))
    confirm = forms.BooleanField(
        label=_("Import the historical observations"), required=False
    )

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > 2_000_000:
            raise forms.ValidationError(_("Maximum file size is 2 MB."))
        return f
