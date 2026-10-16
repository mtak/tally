from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from wealth.models import Account, Entity, Snapshot, TaxAdjustment, Valuation
from wealth.services import movement, report

pytestmark = pytest.mark.django_db


@pytest.fixture
def portfolio():
    company = Entity.objects.create(name="Fictional company", kind="company")
    account = Account.objects.create(name="Example broker", entity=company, kind="broker")
    old = Snapshot.objects.create(date=date(2025, 1, 1), complete=True, imported=True)
    valuation = Valuation.objects.create(snapshot=old, account=account, amount_minor=100000)
    return account, old, valuation


@pytest.fixture
def logged():
    client = Client()
    client.force_login(get_user_model().objects.create_user(username="tester"))
    return client


def payload(account, amount="", basis="", action="complete"):
    return {
        "form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
        "form-0-account_id": str(account.pk), "form-0-amount": amount,
        "form-0-basis": basis, "action": action,
    }


def submit(client, snapshot, data):
    data["editor_version"] = client.get(f"/valuations/{snapshot.pk}/").context["editor_version"]
    return client.post(f"/valuations/{snapshot.pk}/", data)


@pytest.mark.parametrize("overrides", [(), ("bank_ab",), ("broker_vpb",), ("broker_ab",), ("broker_vpb", "broker_ab")])
def test_unknown_tax_and_applicable_overrides(portfolio, overrides):
    account, snapshot, _ = portfolio
    for kind in overrides:
        TaxAdjustment.objects.create(snapshot=snapshot, kind=kind, amount_minor=0)
    snapshot.source_total_minor = 100000
    snapshot.save()
    r = report(snapshot)
    covered = {"broker_vpb", "broker_ab"} <= set(overrides)
    assert r["tax_complete"] is covered
    assert r["total"] == (100000 if covered else None)
    assert r["tax_total"] == (0 if covered else None)
    assert r["groups"]["business"] == r["total"]
    assert r["boxes"]["2"] == r["total"]
    assert r["source_difference"] == (0 if covered else None)
    assert bool(r["warnings"]) is not covered
    for kind in ("broker_vpb", "broker_ab"):
        assert r["tax"][kind] == (0 if kind in overrides else None)
    gross = report(snapshot, net=False)
    assert gross["total"] == gross["gross_total"] == 100000
    assert gross["assets"] == {"cash": 100000}
    assert gross["liquidity"]["liquid"] == 100000


@pytest.mark.parametrize("imported", [False, True])
@pytest.mark.parametrize("carried", [False, True])
@pytest.mark.parametrize("overrides", [(), ("bank_ab",), ("broker_vpb",), ("broker_ab",), ("broker_vpb", "broker_ab")])
@pytest.mark.parametrize("lang", ["en", "nl"])
def test_publish_validates_effective_values(logged, portfolio, imported, carried, overrides, lang):
    account, old, _ = portfolio
    # Older snapshot overrides must not cover a new snapshot's deductions.
    for kind in ("broker_vpb", "broker_ab"):
        TaxAdjustment.objects.create(snapshot=old, kind=kind, amount_minor=-100)
    new = Snapshot.objects.create(date=date(2026, 1, 1), imported=imported)
    for kind in overrides:
        TaxAdjustment.objects.create(snapshot=new, kind=kind, amount_minor=-100)
    logged.cookies["django_language"] = lang
    response = submit(logged, new, payload(account, "" if carried else "1000"))
    covered = {"broker_vpb", "broker_ab"} <= set(overrides)
    assert response.status_code == (302 if covered else 200)
    new.refresh_from_db()
    assert new.complete is covered
    assert new.valuations.count() == (1 if covered and not carried else 0)
    assert list(new.tax_adjustments.values_list("amount_minor", flat=True)) == [-100] * len(overrides)
    if not covered:
        error = str(response.context["formset"][0].errors["basis"])
        assert ("belastinggrondslag" if lang == "nl" else "tax basis") in error


def test_known_carried_basis_and_draft_policy(logged, portfolio):
    account, old, valuation = portfolio
    new = Snapshot.objects.create(date=date(2026, 1, 1))
    assert submit(logged, new, payload(account, "1000", action="draft")).status_code == 302
    new.refresh_from_db()
    assert not new.complete and report(new)["total"] is None
    valuation.basis_minor = 90000
    valuation.save()
    assert submit(logged, new, payload(account)).status_code == 302
    r = report(new)
    assert r["tax_complete"] and r["stale"] == [account.name]
    assert r["tax"]["broker_vpb"] == -1900
    assert r["tax"]["broker_ab"] == -26389
    assert not r["warnings"]


@pytest.mark.parametrize("lang", ["en", "nl"])
def test_incomplete_screens_and_comparisons(logged, portfolio, lang):
    account, old, _ = portfolio
    new = Snapshot.objects.create(date=date(2026, 1, 1), complete=True)
    logged.cookies["django_language"] = lang
    warning = ("Belastinggrondslag ontbreekt: " if lang == "nl" else "Missing tax basis: ") + account.name
    notice = "Onvolledig liquidatiescenario" if lang == "nl" else "Incomplete liquidation scenario"
    for path in ("/", "/analysis/", f"/valuations/{new.pk}/"):
        response = logged.get(path)
        assert response.status_code == 200
        html = response.content.decode()
        assert warning in html and notice in html
    response = logged.get("/")
    assert response.context["change"] is None
    assert all(s["data"] == [None, None] for s in response.context["chart"]["series"])
    assert logged.get("/?net=0").context["current"]["total"] == 100000
    bridge = movement(new)
    assert bridge["incomplete"] and "chart" not in bridge
    # A covered closing snapshot still cannot compare against an unknown opening.
    for kind in ("broker_vpb", "broker_ab"):
        TaxAdjustment.objects.create(snapshot=new, kind=kind, amount_minor=-100)
    assert movement(new)["incomplete"]
    for kind in ("broker_vpb", "broker_ab"):
        TaxAdjustment.objects.create(snapshot=old, kind=kind, amount_minor=-100)
    assert movement(new)["opening"] == movement(new)["closing"] == 99800


def test_unknown_broker_does_not_yield_partial_known_tax_total(portfolio):
    account, snapshot, _ = portfolio
    second = Account.objects.create(name="Known broker", entity=account.entity, kind="broker")
    Valuation.objects.create(snapshot=snapshot, account=second, amount_minor=200000, basis_minor=100000)
    assert report(snapshot)["tax"]["broker_vpb"] is None
    account.pension = True
    account.save()
    assert report(snapshot, include_pension=False)["tax_complete"]
    account.closed_on = snapshot.date
    account.save()
    assert report(snapshot)["tax_complete"]


def test_vpb_override_drives_unoverridden_ab_across_multiple_brokers():
    snap = Snapshot.objects.create(date=date(2026, 1, 1), complete=True)
    owner = Entity.objects.create(name="Example company", kind="company")
    snap.ab_bps = 2690
    snap.vpb_bps = 1900
    snap.save()
    brokers = [Account.objects.create(name=f"Broker {i}", entity=owner, kind="broker")
               for i in range(2)]
    for broker in brokers:
        Valuation.objects.create(snapshot=snap, account=broker,
                                 amount_minor=10001, basis_minor=10000)
    TaxAdjustment.objects.create(snapshot=snap, kind="broker_vpb", amount_minor=101)

    # The override replaces aggregate VPB; AB is rounded once on the combined
    # broker value plus that effective correction.
    assert report(snap)["tax"]["broker_vpb"] == 101
    assert report(snap)["tax"]["broker_ab"] == -5408

    TaxAdjustment.objects.create(snapshot=snap, kind="broker_ab", amount_minor=-77)
    assert report(snap)["tax"]["broker_vpb"] == 101
    assert report(snap)["tax"]["broker_ab"] == -77


def test_movement_tax_correction_labels_are_neutral():
    from django.utils import translation

    from wealth.services import movement

    owner = Entity.objects.create(name="Example company", kind="company")
    snap = Snapshot.objects.create(date=date(2026, 1, 1), complete=True)
    broker = Account.objects.create(name="Broker", entity=owner, kind="broker")
    Valuation.objects.create(snapshot=snap, account=broker, amount_minor=100000,
                             basis_minor=90000)
    later = Snapshot.objects.create(date=date(2026, 2, 1), complete=True)
    Valuation.objects.create(snapshot=later, account=broker, amount_minor=100000,
                             basis_minor=90000)
    TaxAdjustment.objects.create(snapshot=later, kind="broker_vpb", amount_minor=-123)
    TaxAdjustment.objects.create(snapshot=later, kind="broker_ab", amount_minor=-456)

    with translation.override("en"):
        tax = movement(later)["parts"][3]
        assert tax["label"] == "Tax correction change"
        assert {row["label"] for row in tax["details"]} == {
            "VPB on investment gains", "AB after VPB", "AB on bank balances"
        }
        assert all("Portfolio-level tax correction" in row["reason"]
                   for row in tax["details"])
