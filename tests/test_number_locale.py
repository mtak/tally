from decimal import Decimal

import pytest
from django import forms
from django.utils import translation

from wealth.forms import AccountForm, SnapshotForm, ValuationForm
from wealth.numbers import LocalizedDecimalField
from wealth.preferences import show_cents, cents_cookie_name
from wealth.templatetags.money import money, percent
from wealth.models import Account, Entity, Snapshot, Valuation
from tests.test_tally import logged


@pytest.mark.parametrize("lang, inputs", [
    ("nl", ["1.234,56", "1234,56", "-1.234,56", "0", "123.456.789,01", "1.234"]),
    ("en", ["1,234.56", "1234.56", "-1,234.56", "0", "123,456,789.01", "1,234"]),
])
def test_locale_parser(lang, inputs):
    expected = ["1234.56", "1234.56", "-1234.56", "0", "123456789.01", "1234"]
    with translation.override(lang):
        field = LocalizedDecimalField()
        for text, value in zip(inputs, expected):
            assert field.clean(text) == Decimal(value)
        assert field.clean(Decimal("1234.567890123")) == Decimal("1234.567890123")
        assert field.widget.format_value(Decimal("1234.567890123")) == (
            "1.234,567890123" if lang == "nl" else "1,234.567890123")


@pytest.mark.parametrize("lang, inputs", [
    ("nl", ["1,234.56", "1234.56", "12.34,56", "1.23.456", "1,,2", "1,2,3", "1.234,5.6"]),
    ("en", ["1.234,56", "1234,56", "12,34.56", "1,23,456", "1..2", "1.2.3", "1,234.5,6"]),
])
def test_invalid_numbers_are_not_partially_parsed(lang, inputs):
    with translation.override(lang):
        field = LocalizedDecimalField()
        for text in inputs + ["1e3", "NaN", "Infinity", "1 234", "1_234", "€ 123", "--1"]:
            with pytest.raises(forms.ValidationError) as error:
                field.clean(text)
            assert error.value.messages == (["Voer een getal in."] if lang == "nl" else ["Enter a number."])
            assert field.widget.format_value(text) == text


@pytest.mark.parametrize("lang", ["nl", "en"])
def test_percent_forms_and_money_precision(lang):
    with translation.override(lang):
        decimal = "," if lang == "nl" else "."
        assert SnapshotForm.base_fields["ab_rate"].clean("26" + decimal + "90") == Decimal("26.90")
        assert AccountForm.base_fields["interest_rate"].clean("3" + decimal + "45") == Decimal("3.45")
        assert percent(Decimal("26.9")) == "26" + decimal + "90%"
        whole = "1.235" if lang == "nl" else "1,235"
        original = Decimal("1234.56")
        form = ValuationForm({"account_id": 1, "amount": whole}, initial={"amount": original})
        assert form.is_valid(), form.errors
        assert form.cleaned_data["amount"] == original
        token = show_cents.set(False)
        try:
            assert money(123456) == "€ " + whole
            show_cents.set(True)
            assert money(-123456) == ("€ -1.234,56" if lang == "nl" else "€ -1,234.56")
            assert money(0) == "€ 0" + decimal + "00"
        finally:
            show_cents.reset(token)


@pytest.mark.django_db
def test_saved_draft_survives_language_switches(logged):
    from datetime import date
    owner = Entity.objects.create(name="Fictional owner", kind="company")
    account = Account.objects.create(name="Fictional broker", entity=owner, kind="broker")
    snap = Snapshot.objects.create(date=date(2026, 6, 1), complete=False)
    valuation = Valuation.objects.create(account=account, snapshot=snap, amount_minor=123456,
                                        net_deposits_minor=-123456, basis_minor=0)
    path = f"/valuations/{snap.pk}/"
    for cents in [True, False]:
        logged.cookies[cents_cookie_name()] = "1" if cents else "0"
        for lang in ["nl", "en", "nl"]:
            logged.post("/language/setlang/", {"language": lang, "next": path})
            expected = (("1.234,56" if lang == "nl" else "1,234.56") if cents
                        else ("1.235" if lang == "nl" else "1,235"))
            response = logged.get(path, HTTP_HX_REQUEST="true")
            assert f'value="{expected}"' in response.content.decode()
            assert response.headers["Content-Language"] == lang
            data = {"form-TOTAL_FORMS": 1, "form-INITIAL_FORMS": 1,
                    "form-0-account_id": account.pk, "form-0-amount": expected,
                    "form-0-net_deposits": "-" + expected, "form-0-basis": "0", "action": "draft"}
            assert logged.post(path, data).status_code == 302
            valuation.refresh_from_db()
            assert (valuation.amount_minor, valuation.net_deposits_minor, valuation.basis_minor) == (123456, -123456, 0)
            snap.refresh_from_db()
            assert not snap.complete
            data["form-0-amount"] = "12.34,56" if lang == "nl" else "12,34.56"
            assert logged.post(path, data).status_code == 200
            valuation.refresh_from_db()
            assert valuation.amount_minor == 123456


@pytest.mark.parametrize("lang", ["nl", "en"])
def test_overview_source_format_is_independent_of_ui_language(lang):
    from wealth.importer import parse_overview
    from tests.test_tally import fixture_csv
    with translation.override(lang):
        parsed = parse_overview(fixture_csv())
    with translation.override("nl"):
        assert parsed["observations"] == parse_overview(fixture_csv())["observations"]
