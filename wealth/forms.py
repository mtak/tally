from decimal import Decimal, InvalidOperation
from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Account, Entity, Snapshot, Position, ASSETS


def money_field(label, required=False, minimum=None):
    return forms.DecimalField(
        label=label,
        required=required,
        max_digits=16,
        decimal_places=2,
        min_value=minimum,
        localize=True,
        widget=forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off"}),
    )


def minor(value):
    return None if value is None else int(value * 100)


class EntityForm(forms.ModelForm):
    class Meta:
        model = Entity
        fields = ["name", "kind", "parent"]


class AccountForm(forms.ModelForm):
    interest_rate = forms.DecimalField(
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
        widgets = {
            k: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
            for k in ["started_on", "matures_on", "closed_on"]
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["interest_rate"].initial = Decimal(self.instance.rate_bps) / 100

    def clean(self):
        data = super().clean()
        if data.get("joint") and (
            data.get("kind") != "bank"
            or data.get("entity")
            and data["entity"].kind != "private"
        ):
            self.add_error("joint", _("Only a private bank account can be shared."))
        for end in ("closed_on", "matures_on"):
            if (
                data.get("started_on")
                and data.get(end)
                and data[end] < data["started_on"]
            ):
                self.add_error(end, _("This date must be on or after the start date."))
        return data

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
    ab_rate = forms.DecimalField(
        label=_("AB assumption (%)"),
        initial=Decimal("26.90"),
        min_value=0,
        max_value=100,
        decimal_places=2,
        localize=True,
    )
    vpb_rate = forms.DecimalField(
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


class ValuationForm(forms.Form):
    account_id = forms.IntegerField(widget=forms.HiddenInput)
    amount = money_field(_("Value (EUR)"))
    basis = money_field(_("Tax basis / net contributions (EUR)"))
    inflow = money_field(_("Deposits since previous valuation (EUR)"), minimum=0)
    outflow = money_field(_("Withdrawals since previous valuation (EUR)"), minimum=0)
    interest = money_field(_("Interest received or accrued (EUR)"))

    def clean(self):
        data = super().clean()
        if (data.get("inflow") is None) != (data.get("outflow") is None):
            raise forms.ValidationError(
                _(
                    "Enter both deposits and withdrawals, including zero, or leave both blank."
                )
            )
        if data.get("amount") is None and any(
            data.get(x) is not None for x in ("basis", "inflow", "outflow", "interest")
        ):
            raise forms.ValidationError(
                _("Enter a value before entering contributions or a tax basis.")
            )
        return data


class PositionForm(forms.ModelForm):
    value = money_field(_("Position value (EUR)"), required=True, minimum=0)
    quantity = forms.DecimalField(
        label=_("Quantity"),
        required=False,
        max_digits=24,
        decimal_places=10,
        min_value=0,
        localize=True,
    )
    price = forms.DecimalField(
        label=_("Price in original currency"),
        required=False,
        max_digits=24,
        decimal_places=10,
        min_value=0,
        localize=True,
    )

    class Meta:
        model = Position
        fields = [
            "name",
            "asset_class",
            "value",
            "isin",
            "ticker",
            "exchange",
            "currency",
            "quantity",
            "price",
        ]

    def save(self, commit=True):
        obj = super().save(False)
        obj.value_minor = minor(self.cleaned_data["value"])
        for k in ("quantity", "price"):
            val = self.cleaned_data[k]
            setattr(obj, k, "" if val is None else str(val))
        if commit:
            obj.save()
        return obj


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
