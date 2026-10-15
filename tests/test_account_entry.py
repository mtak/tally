from datetime import date

import pytest
from django.utils import translation

from tests.test_tally import logged, owner
from wealth.forms import AccountForm
from wealth.models import Account, Entity, Snapshot, Valuation
from wealth.services import maturity_calendar, movement, report

pytestmark = pytest.mark.django_db


def account_data(owner, **changes):
    return {"name": "Fictional account", "entity": owner.pk, "kind": "claim",
            "asset_class": "deposit", "currency": "EUR", "interest_rate": "3,45",
            "started_on": "05-04-2026", "matures_on": "23-04-2026", "closed_on": "24-04-2026", **changes}


@pytest.mark.parametrize("lang", ["nl", "en"])
def test_account_dates_fixed_format_save_reload_and_errors(logged, owner, lang):
    logged.cookies["django_language"] = lang
    data = account_data(owner)
    assert logged.post("/accounts/new/", data).status_code == 302
    account = Account.objects.get(name=data["name"])
    assert (account.started_on, account.matures_on, account.closed_on) == (
        date(2026, 4, 5), date(2026, 4, 23), date(2026, 4, 24))
    assert account.rate_bps == 345
    response = logged.get(f"/accounts/{account.pk}/")
    page = response.content.decode()
    for value in ("05-04-2026", "23-04-2026", "24-04-2026"):
        assert f'value="{value}"' in page
    assert page.count('data-european-date=""') == 3
    assert 'type="date"' not in page
    assert 'placeholder="dd-mm-yyyy"' in page
    invalid = logged.post(f"/accounts/{account.pk}/", {**data, "matures_on": "31-04-2026"})
    assert invalid.status_code == 200
    assert invalid.context["form"].errors.keys() == {"matures_on"}
    assert 'value="05-04-2026"' in invalid.content.decode()
    assert 'value="31-04-2026"' in invalid.content.decode()
    account.refresh_from_db()
    assert account.matures_on == date(2026, 4, 23)


@pytest.mark.parametrize("lang", ["nl", "en"])
@pytest.mark.parametrize("value", ["04/05/2026", "2026-04-05", "23-13-2026", "29-02-2025"])
def test_account_dates_reject_other_formats_and_invalid_dates(owner, lang, value):
    with translation.override(lang):
        form = AccountForm(account_data(owner, started_on=value))
        assert not form.is_valid()
        assert "started_on" in form.errors


def test_account_dates_optional_leap_day_and_end_validation(owner):
    form = AccountForm(account_data(owner, started_on="29-02-2024", closed_on=""))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["started_on"] == date(2024, 2, 29)
    assert form.cleaned_data["closed_on"] is None
    form = AccountForm(account_data(owner, matures_on="04-04-2026"))
    assert not form.is_valid() and "matures_on" in form.errors


@pytest.mark.parametrize("lang", ["nl", "en"])
def test_account_order_all_overviews_and_rename(logged, owner, lang):
    logged.cookies["django_language"] = lang
    other_owner = Entity.objects.create(name="Another fictional owner", kind="company")
    accounts = [Account.objects.create(name=name, entity=entity, kind="broker")
                for name, entity in [("zebra", owner), ("beta", other_owner),
                                     ("Alpha", owner), ("alpha", other_owner)]]
    expected = [accounts[2], accounts[3], accounts[1], accounts[0]]
    previous = Snapshot.objects.create(date=date(2026, 1, 1), complete=True)
    current = Snapshot.objects.create(date=date(2026, 4, 1), complete=True)
    for index, account in enumerate(accounts):
        for snapshot in (previous, current):
            Valuation.objects.create(account=account, snapshot=snapshot,
                                     amount_minor=10000 + (index*1000 if snapshot == current else 0),
                                     net_deposits_minor=0, basis_minor=0)
    def check(expected):
        assert list(Account.objects.all()) == expected
        for headers in ({}, {"HTTP_HX_REQUEST": "true"}):
            assert list(logged.get("/accounts/", **headers).context["accounts"]) == expected
            dashboard = logged.get("/", **headers).context
            assert [r["account"] for r in dashboard["summary"]["rows"]] == expected
            editor = logged.get(f"/valuations/{current.pk}/", **headers)
            assert [r["account"] for r in editor.context["entries"]] == expected
            analysis = logged.get("/analysis/", **headers)
            assert analysis.context["investment_accounts"] == expected
            assert [r["name"] for r in analysis.context["results"]] == [a.name for a in expected]
        for part in movement(current)["parts"]:
            if part["key"] != "tax":
                rows = [r["account"] for r in part["details"]]
                assert rows == [a for a in expected if a in rows]
    total = report(current)["total"]
    check(expected)
    accounts[0].name = "aardvark"
    accounts[0].save()
    check([accounts[0], *expected[:-1]])
    assert report(current)["total"] == total
    # Calendar sections retain their grouping while account names sort within it.
    Account.objects.update(kind="claim", matures_on=date(2025, 8, 1))
    calendar = maturity_calendar(current)
    assert [r["account"].name for r in calendar["sections"][0]["rows"]] == [
        "aardvark", "Alpha", "alpha", "beta"]
