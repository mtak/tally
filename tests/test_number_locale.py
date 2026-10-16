from decimal import Decimal

import pytest
from django import forms
from django.utils import translation

from wealth.forms import AccountForm, SnapshotForm, ValuationForm
from wealth.numbers import LocalizedDecimalField
from wealth.preferences import show_cents
from wealth.templatetags.money import money, percent
from wealth.models import Account, Entity, Snapshot, Valuation
from tests.test_tally import logged


@pytest.mark.parametrize("lang, inputs", [
    ("nl", ["1.234,56", "1234,56", "-1.234,56", "0", "123.456.789,01", "1234"]),
    ("en", ["1,234.56", "1234.56", "-1,234.56", "0", "123,456,789.01", "1234"]),
])
def test_locale_parser(lang, inputs):
    expected = ["1234.56", "1234.56", "-1234.56", "0", "123456789.01", "1234"]
    with translation.override(lang):
        field = LocalizedDecimalField()
        for text, value in zip(inputs, expected):
            assert field.clean(text) == Decimal(value)
        assert field.clean(Decimal("1234.567890123")) == Decimal("1234.567890123")
        assert field.widget.format_value(Decimal("1234.567890123")) == (
            "1234,567890123" if lang == "nl" else "1234.567890123")


@pytest.mark.parametrize("lang, inputs", [
    ("nl", ["12.34,56", "1.23.456", "1,,2", "1,2,3", "1.234,5.6"]),
    ("en", ["12,34.56", "1,23,456", "1..2", "1.2.3", "1,234.5,6"]),
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
        form = ValuationForm({"account_id": 1, "amount": "1235"}, initial={"amount": original})
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
def test_saved_draft_survives_language_switches(logged, settings):
    from datetime import date
    owner = Entity.objects.create(name="Fictional owner", kind="company")
    account = Account.objects.create(name="Fictional broker", entity=owner, kind="broker")
    snap = Snapshot.objects.create(date=date(2026, 6, 1), complete=False)
    valuation = Valuation.objects.create(account=account, snapshot=snap, amount_minor=123456,
                                        net_deposits_minor=-123456, basis_minor=0)
    path = f"/valuations/{snap.pk}/"
    for cents in [True, False]:
        settings.TALLY_MONEY_PRECISION = "cents" if cents else "whole"
        for lang in ["nl", "en", "nl"]:
            logged.post("/language/setlang/", {"language": lang, "next": path})
            expected = (("1234,56" if lang == "nl" else "1234.56") if cents
                        else "1235")
            response = logged.get(path, HTTP_HX_REQUEST="true")
            assert f'value="{expected}"' in response.content.decode()
            assert response.headers["Content-Language"] == lang
            data = {"form-TOTAL_FORMS": 1, "form-INITIAL_FORMS": 1,
                    "form-0-account_id": account.pk, "form-0-amount": expected,
                    "form-0-net_deposits": "-" + expected, "form-0-basis": "0", "action": "draft"}
            data["editor_version"] = response.context["editor_version"]
            assert logged.post(path, data).status_code == 302
            valuation.refresh_from_db()
            assert (valuation.amount_minor, valuation.net_deposits_minor, valuation.basis_minor) == (123456, -123456, 0)
            snap.refresh_from_db()
            assert not snap.complete
            data["editor_version"] = logged.get(path).context["editor_version"]
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


@pytest.mark.parametrize("lang", ["nl", "en"])
@pytest.mark.parametrize("value, expected", [
    ("12,34", "12.34"), ("12.34", "12.34"), ("-0,25", "-0.25"),
    ("-0.25", "-0.25"), ("0,00", "0"), ("0.00", "0"),
    ("1,234.56", "1234.56"), ("1.234,56", "1234.56"),
    ("1,234,567", "1234567"), ("1.234.567", "1234567"),
])
def test_both_decimal_conventions(lang, value, expected):
    with translation.override(lang):
        form = ValuationForm({"account_id": 1, "amount": value}, show_cents=True)
        assert form.is_valid(), form.errors
        assert form.cleaned_data["amount"] == Decimal(expected)
        if 0 <= Decimal(expected) <= 100:
            assert AccountForm.base_fields["interest_rate"].clean(value) == Decimal(expected)
            assert SnapshotForm.base_fields["ab_rate"].clean(value) == Decimal(expected)
        assert 'type="text"' in str(form["amount"])
        assert 'pattern=' not in str(form["amount"])


@pytest.mark.parametrize("lang", ["nl", "en"])
@pytest.mark.parametrize("value", ["1,234", "1.234", "-12,345", "123.456"])
def test_ambiguous_numbers_require_explicit_input(lang, value):
    with translation.override(lang):
        with pytest.raises(forms.ValidationError) as error:
            LocalizedDecimalField().clean(value)
        assert error.value.error_list[0].code == "ambiguous"


@pytest.mark.django_db
@pytest.mark.parametrize("lang", ["nl", "en"])
@pytest.mark.parametrize("separator", [",", "."])
def test_alternate_decimals_save_and_reload(logged, settings, lang, separator):
    from datetime import date
    logged.cookies["django_language"] = lang
    settings.TALLY_MONEY_PRECISION = "cents"
    owner = Entity.objects.create(name="Fictional owner", kind="private")
    account = Account.objects.create(name="Fictional account", entity=owner)
    snapshot = Snapshot.objects.create(date=date(2026, 4, 5))
    path = f"/valuations/{snapshot.pk}/"
    response = logged.get(path)
    data = {"editor_version": response.context["editor_version"], "action": "draft",
            "form-TOTAL_FORMS": 1, "form-INITIAL_FORMS": 1,
            "form-0-account_id": account.pk, "form-0-amount": "12"+separator+"34",
                "form-0-interest": "-0"+separator+"25",
                "form-0-interest_period_start": "04-04-2026",
                "form-0-interest_period_end": "05-04-2026"}
    assert logged.post(path, data).status_code == 302
    value = Valuation.objects.get(account=account)
    assert (value.amount_minor, value.interest_minor) == (1234, -25)
    page = logged.get(path).content.decode()
    assert ('value="12,34"' if lang == "nl" else 'value="12.34"') in page
