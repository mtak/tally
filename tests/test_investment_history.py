from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import translation

from wealth.models import Account, Entity, Snapshot, TaxAdjustment, Valuation
from wealth.services import investment_history
from wealth.preferences import cents_cookie_name

pytestmark = pytest.mark.django_db


@pytest.fixture
def history_account():
    owner = Entity.objects.create(name="Fictional holding", kind="company")
    account = Account.objects.create(name="Fictional broker", entity=owner, kind="broker",
                                     closed_on=date(2026, 9, 1))
    for month, day, value, deposits in [(1, 3, 11800000, 10000000), (2, 19, 10800000, 9000000),
                                      (4, 1, 10800001, None), (7, 11, 1800001, 0),
                                      (8, 20, 800001, -1000000)]:
        snapshot = Snapshot.objects.create(date=date(2026, month, day), complete=True, imported=True)
        Valuation.objects.create(account=account, snapshot=snapshot, amount_minor=value,
                                 net_deposits_minor=deposits)
        TaxAdjustment.objects.create(snapshot=snapshot, kind="broker_vpb", amount_minor=-234567)
    draft = Snapshot.objects.create(date=date(2026, 3, 1))
    Valuation.objects.create(account=account, snapshot=draft, amount_minor=99999999, net_deposits_minor=0)
    # An unrelated published valuation must not create a carried account point.
    Snapshot.objects.create(date=date(2026, 5, 1), complete=True)
    return account


def test_history_uses_actual_published_dates_and_gross_results(history_account):
    taxes = list(TaxAdjustment.objects.values_list("pk", "amount_minor"))
    history = investment_history(history_account, date(2026, 10, 1))
    assert history["chart"]["dates"] == ["2026-01-03", "2026-02-19", "2026-04-01", "2026-07-11", "2026-08-20"]
    assert [r["cumulative_result"] for r in history["rows"]] == [1800000, 1800000, None, 1800001, 1800001]
    for key, series in zip(("amount", "net_deposits", "cumulative_result"), history["chart"]["series"]):
        assert series["data"] == [r[key] for r in history["rows"]]
    assert list(TaxAdjustment.objects.values_list("pk", "amount_minor")) == taxes
    first = investment_history(history_account, date(2026, 1, 3))
    assert len(first["rows"]) == 1 and first["rows"][0]["cumulative_result"] == 1800000
    assert investment_history(history_account, date(2025, 12, 31))["rows"] == []


@pytest.mark.parametrize("language", ["en", "nl"])
def test_analysis_selectors_table_locale_and_empty_history(history_account, language):
    client = Client()
    client.cookies["django_language"] = language
    client.force_login(get_user_model().objects.create_user(username="fictional-tester"))
    other = Account.objects.create(name="Other fictional broker", entity=history_account.entity, kind="broker")
    bank = Account.objects.create(name="Fictional bank", entity=history_account.entity)
    snapshot = Snapshot.objects.get(date=date(2026, 7, 11))
    with translation.override(language):
        response = client.get("/analysis/", {"at": snapshot.pk, "account": history_account.pk})
        assert response.status_code == 200
        assert response.context["selected_account"] == history_account
        assert len(response.context["investment_history"]["rows"]) == 4
        content = response.content.decode()
        assert 'name="account"' in content and 'id="investment-chart"' in content
        assert 'tabindex="0" role="region"' in content
        assert ("18.000" if language == "nl" else "18,000") in content
        assert ("Netto-inleg onbekend" if language == "nl" else "Net deposits unknown") in content
        client.cookies[cents_cookie_name()] = "1"
        precise = client.get("/analysis/", {"at": snapshot.pk, "account": history_account.pk})
        assert ("18.000,01" if language == "nl" else "18,000.01") in precise.content.decode()
        empty = client.get("/analysis/", {"at": snapshot.pk, "account": other.pk})
        assert empty.context["investment_history"]["rows"] == []
        assert 'id="investment-chart"' not in empty.content.decode()
        invalid = client.get("/analysis/", {"at": snapshot.pk, "account": bank.pk})
        assert invalid.context["selected_account"] == history_account
