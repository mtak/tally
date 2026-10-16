import csv
import io
from datetime import date

import pytest
from django.test import Client

from tests.test_tally import logged, owner
from tests.test_editor_conflicts import body
from wealth.forms import AccountForm
from wealth.models import Account, Entity, Snapshot, TaxAdjustment, Valuation

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("lang", ["en", "nl"])
@pytest.mark.parametrize("cents", ["0", "1"])
def test_export_preserves_interest_exactly(logged, owner, settings, lang, cents):
    settings.TALLY_MONEY_PRECISION = "cents" if cents == "1" else "whole"
    logged.cookies["django_language"] = lang
    for kind in ("bank", "claim"):
        account = Account.objects.create(name=f"=Fictional {kind}", entity=owner, kind=kind)
        for index, interest in enumerate((None, 0, 1234, -567)):
            snapshot, _ = Snapshot.objects.get_or_create(
                date=date(2026, index + 1, 1), defaults={"complete": index % 2 == 0})
            Valuation.objects.create(account=account, snapshot=snapshot,
                                     amount_minor=123456, interest_minor=interest,
                                     **({"interest_period_start": date(2026, 2, 1),
                                        "interest_period_end": date(2026, 3, 1)}
                                        if index == 2 else {}))
    before = list(Valuation.objects.order_by("pk").values())
    rows = list(csv.DictReader(io.StringIO(logged.get("/export/").content.decode())))
    assert len(rows) == 8
    for kind in ("bank", "claim"):
        selected = [r for r in rows if r["account"] == f"'=Fictional {kind}"]
        assert [r["interest_eur"] for r in selected] == ["", "0", "12.34", "-5.67"]
        assert [r["interest_period_start"] for r in selected] == ["", "", "2026-02-01", ""]
        assert [r["interest_period_end"] for r in selected] == ["", "", "2026-03-01", ""]
        assert [r["status"] for r in selected] == ["published", "draft", "published", "draft"]
        assert all(r["value_eur"] == "1234.56" for r in selected)
    assert list(Valuation.objects.order_by("pk").values()) == before


@pytest.mark.parametrize("lang", ["en", "nl"])
@pytest.mark.parametrize("kind,company", [("bank", False), ("claim", False), ("broker", True), ("property", False)])
@pytest.mark.parametrize("cents", ["0", "1"])
def test_history_only_actual_observations_and_no_mutation(logged, owner, settings, lang, kind, company, cents):
    settings.TALLY_MONEY_PRECISION = "cents" if cents == "1" else "whole"
    logged.cookies["django_language"] = lang
    if company:
        owner.kind = "company"
        owner.save()
    account = Account.objects.create(name="Fictional history", entity=owner, kind=kind,
                                     joint=kind == "bank", closed_on=date(2026, 9, 1))
    observations = []
    for month, complete, imported, detail in [(1, True, True, None), (4, False, False, 0), (7, True, False, -1234)]:
        snapshot = Snapshot.objects.create(date=date(2026, month, 1), complete=complete, imported=imported)
        observations.append(Valuation.objects.create(snapshot=snapshot, account=account,
                            amount_minor=123456 if month == 1 else 0,
                            basis_minor=detail, net_deposits_minor=detail, interest_minor=detail))
    # No saved observation on this date, even though reporting could carry a balance.
    Snapshot.objects.create(date=date(2025, 8, 1), complete=True)
    TaxAdjustment.objects.create(snapshot=observations[0].snapshot, kind="bank_ab", amount_minor=-789)
    before = (list(Valuation.objects.order_by("pk").values()), list(Snapshot.objects.values()),
              list(Account.objects.values()), list(TaxAdjustment.objects.values()))
    path = f"/accounts/{account.pk}/history/"
    assert Client().get(path).status_code == 302
    response = logged.get(path)
    assert response.status_code == 200
    assert list(response.context["observations"]) == observations[::-1]
    page = response.content.decode()
    assert ("Geschiedenis" if lang == "nl" else "History") in page
    assert ("Geïmporteerd" if lang == "nl" else "Imported") in page
    assert ("Concept" if lang == "nl" else "Draft") in page
    assert ("Gesloten" if lang == "nl" else "Closed") in page
    value = {("en", "0"): "€ 1,235", ("en", "1"): "€ 1,234.56",
             ("nl", "0"): "€ 1.235", ("nl", "1"): "€ 1.234,56"}[lang, cents]
    assert value in page  # Full value, even for the joint bank account.
    assert ("€ 0" if cents == "0" else ("€ 0,00" if lang == "nl" else "€ 0.00")) in page
    if kind != "property":
        assert 'class="number">—</td>' in page
        assert ("€ -12" if cents == "0" else ("€ -12,34" if lang == "nl" else "€ -12.34")) in page
    assert ("Net deposits since opening (EUR)" in page) == (kind == "broker" and lang == "en")
    for observation in observations:
        assert f'href="/valuations/{observation.snapshot_id}/"' in page
    assert logged.post(path, {}).status_code == 405
    after = (list(Valuation.objects.order_by("pk").values()), list(Snapshot.objects.values()),
             list(Account.objects.values()), list(TaxAdjustment.objects.values()))
    assert after == before


@pytest.mark.parametrize("lang", ["en", "nl"])
def test_empty_history_discoverable_and_missing_account(logged, owner, lang):
    logged.cookies["django_language"] = lang
    account = Account.objects.create(name="Fictional empty", entity=owner)
    path = f"/accounts/{account.pk}/history/"
    assert f'href="{path}"' in logged.get("/accounts/").content.decode()
    page = logged.get(path).content.decode()
    assert ("Nog geen vastgelegde waarnemingen" if lang == "nl" else "No recorded observations") in page
    assert logged.get("/accounts/999999/history/").status_code == 404


@pytest.mark.parametrize("lang", ["en", "nl"])
def test_owner_order_filter_validation_save_and_stale_mapping(logged, owner, lang):
    logged.cookies["django_language"] = lang
    owner.name = "zeta owner"
    owner.save()
    early = Entity.objects.create(name="Alpha owner", kind="private")
    tied = Entity.objects.create(name="alpha owner", kind="private")
    accounts = [Account.objects.create(name=name, entity=entity) for name, entity in
                [("zebra", early), ("alpha", owner), ("Alpha", early), ("beta", tied)]]
    Account.objects.create(name="Excluded closed", entity=early, closed_on=date(2026, 1, 1))
    Account.objects.create(name="Excluded future", entity=early, started_on=date(2027, 1, 1))
    snapshot = Snapshot.objects.create(date=date(2026, 1, 1))
    expected = [accounts[2], accounts[0], accounts[3], accounts[1]]
    path = f"/valuations/{snapshot.pk}/"
    for headers in ({}, {"HTTP_HX_REQUEST": "true"}):
        entries = logged.get(path, **headers).context["entries"]
        assert [e["account"] for e in entries] == expected
    data = body(logged, snapshot)
    for index in range(4):
        data[f"form-{index}-amount"] = str(100 + index)
    invalid = {**data, "form-0-amount": "invalid"}
    response = logged.post(path, invalid)
    assert response.status_code == 200
    assert [e["account"] for e in response.context["entries"]] == expected
    assert logged.post(path, data).status_code == 302
    assert [(v.account_id, v.amount_minor) for v in snapshot.valuations.order_by("amount_minor")] == [
        (a.pk, (100+i)*100) for i, a in enumerate(expected)]
    stale = body(logged, snapshot)
    # Changing both owner and name changes fresh order but must not relabel stale inputs.
    accounts[0].entity = owner
    accounts[0].name = "A renamed bank"
    accounts[0].save()
    before = list(snapshot.valuations.order_by("pk").values())
    response = logged.post(path, stale)
    assert response.status_code == 409
    entries = response.context["entries"]
    assert [e["account"].pk for e in entries] == [a.pk for a in expected]
    assert entries[1]["account"].name == "zebra"
    assert entries[1]["account"].entity.name == "Alpha owner"
    for index, entry in enumerate(entries):
        assert entry["form"]["amount"].value() == stale[f"form-{index}-amount"]
    assert list(snapshot.valuations.order_by("pk").values()) == before
    assert [e["account"].pk for e in logged.get(path).context["entries"]] == [
        accounts[2].pk, accounts[3].pk, accounts[0].pk, accounts[1].pk]
    listing = list(logged.get("/accounts/").context["accounts"])
    assert listing == sorted(listing, key=lambda a: (a.entity.name.lower(), a.entity_id, a.name.lower(), a.pk))
    # Exact duplicate account names still fail across different owners.
    form = AccountForm({"name": "Alpha", "entity": owner.pk, "kind": "bank", "asset_class": "cash", "currency": "EUR"})
    assert not form.is_valid() and "name" in form.errors
