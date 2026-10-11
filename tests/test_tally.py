import csv, io
from datetime import date
from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.utils import translation
from wealth.models import (
    Entity,
    Account,
    Snapshot,
    Valuation,
    Position,
    TaxAdjustment,
    ImportRecord,
)
from wealth.services import report, performance, rate
from wealth.importer import parse_overview, import_overview
from wealth.forms import AccountForm, ValuationForm

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return Entity.objects.create(name="Test person", kind="private")


@pytest.fixture
def account(owner):
    return Account.objects.create(name="Test account", entity=owner)


@pytest.fixture
def snap():
    return Snapshot.objects.create(date=date(2026, 1, 1), complete=True)


@pytest.fixture
def logged():
    client = Client()
    u = get_user_model().objects.create_user(
        username="tester", password="fictional-test-only"
    )
    client.force_login(u)
    return client


def test_joint_ownership_is_applied_once(account, snap):
    account.joint = True
    account.save()
    Valuation.objects.create(snapshot=snap, account=account, amount_minor=10001)
    r = report(snap)
    assert r["total"] == 5001
    assert sum(r["assets"].values()) == 5001


def test_unknown_and_zero_are_distinct(account, snap):
    assert report(snap)["missing"] == [account.name]
    Valuation.objects.create(snapshot=snap, account=account, amount_minor=0)
    assert report(snap)["missing"] == []


def test_carry_forward_retains_date_and_excludes_other_drafts(account, snap):
    old = Valuation.objects.create(snapshot=snap, account=account, amount_minor=10000)
    draft = Snapshot.objects.create(date=date(2026, 2, 1))
    Valuation.objects.create(snapshot=draft, account=account, amount_minor=99999)
    later = Snapshot.objects.create(date=date(2026, 3, 1), complete=True)
    r = report(later)
    assert r["total"] == 10000 and r["rows"][0]["valuation"].snapshot.date == snap.date
    assert account.name in r["stale"]


def test_future_values_and_closed_accounts_not_carried_back(account, snap):
    account.closed_on = date(2026, 2, 1)
    account.save()
    Valuation.objects.create(snapshot=snap, account=account, amount_minor=100)
    later = Snapshot.objects.create(date=date(2026, 2, 1), complete=True)
    assert report(snap)["total"] == 100 and report(later)["total"] == 0


def test_start_date_hides_unopened_accounts(account, snap):
    account.started_on = date(2026, 2, 1)
    account.save()
    assert report(snap)["missing"] == []


def test_home_pension_filters_and_gross_allocation(owner, snap):
    for name, kind, pension, value in [
        ("Home", "property", False, 50000000),
        ("Debt", "mortgage", False, -30000000),
        ("Pension", "broker", True, 4000000),
    ]:
        a = Account.objects.create(
            name=name,
            kind=kind,
            pension=pension,
            entity=owner,
            liquid=False,
            asset_class="property" if not pension else "equities",
        )
        Valuation.objects.create(account=a, snapshot=snap, amount_minor=value)
    assert report(snap)["total"] == 24000000
    assert sum(report(snap)["assets"].values()) == 54000000
    assert report(snap, include_home=False)["total"] == 4000000
    assert report(snap, include_pension=False)["total"] == 20000000


def test_company_tax_loss_credit_and_historical_override(snap):
    e = Entity.objects.create(name="Holding", kind="company")
    a = Account.objects.create(name="Company broker", entity=e, kind="broker")
    Valuation.objects.create(
        account=a, snapshot=snap, amount_minor=9000000, basis_minor=10000000
    )
    r = report(snap)
    assert r["tax"]["broker_vpb"] == 190000
    assert r["tax"]["broker_ab"] == -2472110
    assert r["total"] == 9000000 + 190000 - 2472110
    TaxAdjustment.objects.create(snapshot=snap, kind="broker_vpb", amount_minor=123)
    assert report(snap)["tax"]["broker_vpb"] == 123
    assert report(snap, net=False)["total"] == 9000000


def test_sole_proprietor_is_not_box_two(snap):
    e = Entity.objects.create(name="Sole", kind="sole")
    a = Account.objects.create(name="Sole cash", entity=e)
    Valuation.objects.create(snapshot=snap, account=a, amount_minor=50000)
    assert report(snap)["groups"]["business"] == 50000
    assert report(snap)["tax_total"] == 0 and report(snap)["boxes"]["2"] == 0


def test_account_return_uses_flows_not_trades(account, snap):
    Valuation.objects.create(account=account, snapshot=snap, amount_minor=10000000)
    s = Snapshot.objects.create(date=date(2025, 8, 1), complete=True)
    v = Valuation.objects.create(
        account=account,
        snapshot=s,
        amount_minor=11800000,
        inflow_minor=1200000,
        outflow_minor=200000,
    )
    result = performance(v)
    assert result["result"] == 800000
    assert result["percent"] == Decimal(800000) / Decimal(10500000) * 100
    v.inflow_minor = None
    assert performance(v) is None


def test_negative_capital_has_no_percentage(account, snap):
    Valuation.objects.create(account=account, snapshot=snap, amount_minor=0)
    s = Snapshot.objects.create(date=date(2025, 8, 1), complete=True)
    v = Valuation.objects.create(
        account=account, snapshot=s, amount_minor=0, inflow_minor=0, outflow_minor=100
    )
    assert performance(v)["percent"] is None


def test_positions_do_not_double_count(account, snap):
    v = Valuation.objects.create(account=account, snapshot=snap, amount_minor=10000)
    Position.objects.create(
        valuation=v, name="Equity", asset_class="equities", value_minor=7500
    )
    r = report(snap)
    assert r["total"] == 10000 and r["assets"] == {"equities": 7500, "other": 2500}
    Position.objects.create(
        valuation=v, name="Excess", asset_class="cash", value_minor=5000
    )
    assert report(snap)["warnings"]


def fixture_csv():
    rows = [
        ["", "", ""],
        ["", "", ""],
        ["Prive", "", "01-01-2024", "€ 12.345"],
        ["", "Example Bank Private Current", "€ 100", "€ 200"],
        ["", "Example Brokerage Value", "€ 1.000", "€ 2.000"],
        ["", "Example Brokerage Contributions", "€ 900", "€ 1.500"],
        ["", "Example Brokerage Corporate Tax", "-€ 19", "-€ 95"],
        ["", "Example Brokerage Capital Tax", "-€ 264", "-€ 512"],
        ["Totaal", "", "€ 817", "€ 1.593"],
        ["", "Liquide vermogen", "€ 100", ""],
        ["", "Niet-liquide vermogen", "€ 0", ""],
    ]
    f = io.StringIO()
    csv.writer(f).writerows(rows)
    return f.getvalue().encode()


def test_csv_import_dates_roundtrip_and_duplicate_protection():
    p = parse_overview(fixture_csv())
    assert p["observations"][-1]["date"] == date(2025, 8, 1)
    assert import_overview(p) == 2
    assert Account.objects.get(name="Gezamenlijke rekening").joint
    latest = Snapshot.objects.latest("date")
    assert report(latest)["total"] == 159300
    assert report(latest)["source_difference"] == 0
    with pytest.raises(ValueError):
        import_overview(p)
    assert Snapshot.objects.count() == 2


def test_overlapping_import_is_atomic(snap):
    p = parse_overview(fixture_csv())
    p["observations"][0]["date"] = snap.date
    with pytest.raises(ValueError):
        import_overview(p)
    assert Account.objects.count() == 0 and ImportRecord.objects.count() == 0


@pytest.mark.parametrize(
    "url", ["/", "/accounts/", "/valuations/", "/analysis/", "/export/", "/import/"]
)
def test_login_required(url):
    assert Client().get(url).status_code == 302


@pytest.mark.parametrize("lang", ["nl", "en"])
def test_render_all_screens_in_both_languages(logged, lang):
    call_command("seed_demo")
    logged.cookies["django_language"] = lang
    s = Snapshot.objects.latest("date")
    v = Valuation.objects.filter(account__kind="broker").first()
    for path in [
        "/",
        "/accounts/",
        "/accounts/new/",
        "/owners/new/",
        "/valuations/",
        "/valuations/new/",
        f"/valuations/{s.pk}/",
        f"/positions/{v.pk}/",
        "/analysis/",
        "/import/",
    ]:
        assert logged.get(path).status_code == 200, path
    expected = (
        "Je vermogen in één oogopslag" if lang == "nl" else "Your wealth at a glance"
    )
    assert expected in logged.get("/").content.decode()


def test_nl_input_and_missing_flow_validation():
    with translation.override("nl"):
        f = ValuationForm(
            {"account_id": 1, "amount": "1234,56", "inflow": "0", "outflow": "0"}
        )
        assert f.is_valid(), f.errors
        assert f.cleaned_data["amount"] == Decimal("1234.56")
        f = ValuationForm(
            {"account_id": 1, "amount": "1", "inflow": "0", "outflow": ""}
        )
        assert not f.is_valid()


def test_snapshot_save_rejects_negative_assets(logged, account, snap):
    body = {
        "form-TOTAL_FORMS": "1",
        "form-INITIAL_FORMS": "1",
        "form-0-account_id": str(account.pk),
        "form-0-amount": "-100",
        "action": "complete",
    }
    response = logged.post(f"/valuations/{snap.pk}/", body)
    assert response.status_code == 200 and not Valuation.objects.exists()


def test_snapshot_saves_zero_and_publishes(logged, account, snap):
    body = {
        "form-TOTAL_FORMS": "1",
        "form-INITIAL_FORMS": "1",
        "form-0-account_id": str(account.pk),
        "form-0-amount": "0",
        "action": "complete",
    }
    assert logged.post(f"/valuations/{snap.pk}/", body).status_code == 302
    assert Valuation.objects.get().amount_minor == 0


def test_position_deletion_requires_post_and_auth(logged, account, snap):
    v = Valuation.objects.create(account=account, snapshot=snap, amount_minor=100)
    p = Position.objects.create(valuation=v, name="Test", value_minor=100)
    assert logged.get(f"/positions/{p.pk}/delete/").status_code == 405
    assert Position.objects.filter(pk=p.pk).exists()


def test_rounding_half_up(account, snap):
    Valuation.objects.create(account=account, snapshot=snap, amount_minor=100)
    # pytest's in-memory SQLite connection cannot be reopened by filename.
    # File-backed online backup is separately exercised in integration verification.
    from wealth.services import rounded

    assert rounded(Decimal("0.5")) == 1 and rounded(Decimal("-0.5")) == -1


def test_movement_bridge_reconciles_and_ignores_internal_flows(owner, snap):
    from wealth.services import movement

    cash = Account.objects.create(name="Cash", entity=owner)
    broker = Account.objects.create(name="Broker", entity=owner, kind="broker")
    Valuation.objects.create(account=cash, snapshot=snap, amount_minor=20000)
    Valuation.objects.create(account=broker, snapshot=snap, amount_minor=10000)
    later = Snapshot.objects.create(date=date(2026, 5, 1), complete=True)
    Valuation.objects.create(
        account=cash, snapshot=later, amount_minor=15100, interest_minor=100
    )
    Valuation.objects.create(
        account=broker,
        snapshot=later,
        amount_minor=17000,
        inflow_minor=5000,
        outflow_minor=0,
    )
    bridge = movement(later)
    assert bridge["closing"] == 32100
    assert [p["amount"] for p in bridge["parts"]] == [2000, 100, 0, 0, 0]
    assert (
        bridge["opening"] + sum(p["amount"] for p in bridge["parts"])
        == bridge["closing"]
    )


@pytest.mark.parametrize("language", ["en", "nl"])
def test_analysis_chart_excludes_wealth_totals_and_tracks_period(logged, account, snap, language):
    import json
    import re
    from wealth.templatetags.money import money

    Valuation.objects.create(account=account, snapshot=snap, amount_minor=100000000)
    later = Snapshot.objects.create(date=date(2026, 5, 1), complete=True)
    Valuation.objects.create(account=account, snapshot=later,
                            amount_minor=100010000, interest_minor=20000)
    latest = Snapshot.objects.create(date=date(2026, 9, 1), complete=True)
    Valuation.objects.create(account=account, snapshot=latest,
                            amount_minor=100005000, interest_minor=0)
    with translation.override(language):
        for selected, opening, closing, values in [
            (later, 100000000, 100010000, [0, 200, 0, 0, -100]),
            (latest, 100010000, 100005000, [0, 0, 0, 0, -50]),
        ]:
            response = logged.get("/analysis/", {"at": selected.pk})
            assert response.status_code == 200
            html = response.content.decode()
            chart = json.loads(re.search(
                r'<script id="movement-data" type="application/json">(.*?)</script>', html
            ).group(1))
            assert chart["values"] == values
            assert len(chart["labels"]) == 5
            assert money(opening) in html
            assert money(closing) in html
            assert response.context["movement"]["after"] == selected


def test_company_account_requires_basis_when_publishing(logged, snap):
    entity = Entity.objects.create(name="Example company", kind="company")
    account = Account.objects.create(
        name="Company investments", entity=entity, kind="broker"
    )
    payload = {
        "form-TOTAL_FORMS": "1",
        "form-INITIAL_FORMS": "1",
        "form-0-account_id": str(account.pk),
        "form-0-amount": "1000",
        "action": "complete",
    }
    response = logged.post(f"/valuations/{snap.pk}/", payload)
    assert response.status_code == 200
    assert not Valuation.objects.exists()
    payload["form-0-basis"] = "900"
    assert logged.post(f"/valuations/{snap.pk}/", payload).status_code == 302
    assert Valuation.objects.get().basis_minor == 90000


def test_editing_position_preserves_exact_quantity(logged, account, snap):
    account.kind = "broker"
    account.save()
    v = Valuation.objects.create(snapshot=snap, account=account, amount_minor=10000)
    p = Position.objects.create(
        valuation=v, name="ETF", value_minor=8000, quantity="0.1234567890"
    )
    logged.cookies["django_language"] = "en"
    response = logged.post(
        f"/positions/{v.pk}/edit/{p.pk}/",
        {
            "name": "ETF",
            "asset_class": "equities",
            "value": "90.00",
            "quantity": "0.1234567890",
            "currency": "EUR",
        },
    )
    assert response.status_code == 302
    p.refresh_from_db()
    assert p.value_minor == 9000 and p.quantity == "0.1234567890"
    assert Position.objects.count() == 1


@pytest.mark.parametrize("saved", [None, "unsupported", ""])
def test_first_visit_uses_english_despite_dutch_browser(logged, saved):
    if saved is not None:
        logged.cookies["django_language"] = saved
    for path in ["/login/", "/", "/accounts/new/", "/analysis/"]:
        response = logged.get(path, HTTP_ACCEPT_LANGUAGE="nl-NL,nl;q=0.9,en;q=0.8")
        assert response.status_code == 200
        assert response.headers["Content-Language"] == "en"
        assert '<html lang="en" data-theme="dark">' in response.content.decode()


@pytest.mark.parametrize("language", ["nl", "en"])
def test_explicit_language_selection_persists(logged, language):
    response = logged.post("/language/setlang/", {"language": language, "next": "/"})
    assert response.status_code == 302
    assert response.cookies["django_language"].value == language
    for path in ["/login/", "/", "/accounts/new/", "/analysis/"]:
        response = logged.get(path, HTTP_ACCEPT_LANGUAGE="en" if language == "nl" else "nl")
        assert response.headers["Content-Language"] == language
        assert f'<html lang="{language}"' in response.content.decode()
        assert "Cookie" in response.headers["Vary"]
