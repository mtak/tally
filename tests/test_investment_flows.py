from datetime import date
from decimal import Decimal
import csv
import io

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import translation
from wealth.models import Entity, Account, Snapshot, Valuation, TaxAdjustment
from wealth.services import performance, movement
from wealth.forms import ValuationForm

pytestmark = pytest.mark.django_db

@pytest.fixture
def setup():
    owner = Entity.objects.create(name="Fictional owner", kind="private")
    account = Account.objects.create(name="Fictional broker", kind="broker", entity=owner)
    start = Snapshot.objects.create(date=date(2026, 1, 1), complete=True)
    opening = Valuation.objects.create(account=account, snapshot=start, amount_minor=10000000)
    end = Snapshot.objects.create(date=date(2026, 6, 1))
    client = Client()
    user = get_user_model().objects.create_user(username="flows", password="fictional-only")
    client.force_login(user)
    return client, account, opening, end

def submit(setup, **fields):
    client, account, opening, end = setup
    body = {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
            "form-0-account_id": str(account.pk), "form-0-amount": "118000",
            "form-0-flow_mode": "period", "form-0-flow_start": opening.snapshot.date.isoformat(),
            "action": "complete"}
    body.update({"form-0-" + key: value for key, value in fields.items()})
    return client.post(f"/valuations/{end.pk}/", body)

def counters(opening):
    opening.flow_mode = "cumulative"
    opening.cumulative_inflow_minor = 10000000
    opening.cumulative_outflow_minor = 0
    opening.cumulative_baseline_date = opening.snapshot.date
    opening.flow_end_date = opening.snapshot.date
    opening.save()

@pytest.mark.parametrize("lang", ["en", "nl"])
def test_no_flows_shortcut_and_unknown(setup, lang):
    with translation.override(lang):
        assert submit(setup, no_flows="on", amount="110000").status_code == 302
        value = Valuation.objects.get(snapshot=setup[3])
        assert value.inflow_minor == value.outflow_minor == 0
        assert performance(value)["result"] == 1000000
        assert performance(value)["percent"] == Decimal(10)
        assert submit(setup, inflow="", outflow="").status_code == 302
        value.refresh_from_db()
        assert performance(value) is None

@pytest.mark.parametrize("mode", ["period", "cumulative"])
def test_backdated_observation_and_resave_keep_endpoints(setup, mode):
    client, account, opening, end = setup
    if mode == "cumulative":
        counters(opening)
        fields = dict(flow_mode=mode, cumulative_start="2026-01-01", cumulative_inflow="112000", cumulative_outflow="2000")
    else:
        fields = dict(inflow="12000", outflow="2000")
    assert submit(setup, **fields).status_code == 302
    value = Valuation.objects.get(snapshot=end)
    assert performance(value)["result"] == 800000
    middle = Snapshot.objects.create(date=date(2026, 3, 1), complete=True)
    Valuation.objects.create(account=account, snapshot=middle, amount_minor=10500000)
    assert performance(value)["result"] == 800000
    page = client.get(f"/valuations/{end.pk}/")
    key = "cumulative_start" if mode == "cumulative" else "flow_start"
    assert page.context["formset"].forms[0].initial[key] == "2026-01-01"
    assert submit(setup, **fields).status_code == 302
    value.refresh_from_db()
    assert performance(value)["since"] == opening.snapshot.date
    assert performance(value)["result"] == 800000
    assert movement(end)["parts"][0]["amount"] == 0

def test_cumulative_baseline_corrections_and_mode_switches(setup):
    client, account, opening, end = setup
    assert submit(setup, inflow="12000", outflow="2000").status_code == 302
    value = Valuation.objects.get(snapshot=end)
    assert submit(setup, flow_mode="cumulative", cumulative_start="", cumulative_inflow="112000", cumulative_outflow="2000").status_code == 302
    value.refresh_from_db()
    assert performance(value) is None
    assert value.inflow_minor == 1200000 and value.outflow_minor == 200000
    assert value.flow_start_date == opening.snapshot.date
    assert value.cumulative_baseline_date == end.date
    later = Snapshot.objects.create(date=date(2026, 9, 1))
    next_setup = (client, account, value, later)
    assert submit(next_setup, flow_mode="cumulative", cumulative_start=end.date.isoformat(), cumulative_inflow="111000", cumulative_outflow="2000").status_code == 200
    assert not Valuation.objects.filter(snapshot=later).exists()
    assert submit(next_setup, flow_mode="cumulative", cumulative_start="", cumulative_inflow="111000", cumulative_outflow="2000").status_code == 302
    assert performance(Valuation.objects.get(snapshot=later)) is None
    assert submit(setup, inflow="12000", outflow="2000").status_code == 302
    value.refresh_from_db()
    assert performance(value)["result"] == 800000
    assert value.cumulative_inflow_minor == 11200000

def test_missing_opening_or_changed_counter_endpoint_cannot_claim_return(setup):
    client, account, opening, end = setup
    counters(opening)
    assert submit(setup, flow_mode="cumulative", cumulative_start="2026-01-01", cumulative_inflow="112000", cumulative_outflow="2000").status_code == 302
    value = Valuation.objects.get(snapshot=end)
    opening.cumulative_inflow_minor = 11300000
    opening.save()
    assert performance(value) is None
    opening.cumulative_inflow_minor = 10000000
    opening.cumulative_baseline_date = date(2025, 1, 1)
    opening.save()
    assert performance(value) is None
    opening.delete()
    assert performance(value) is None

def test_invalid_start_and_conflicting_zero_shortcut(setup):
    assert submit(setup, flow_start="2024-01-01", inflow="0", outflow="0").status_code == 200
    assert submit(setup, no_flows="on", inflow="100", outflow="0").status_code == 200
    assert not Valuation.objects.filter(snapshot=setup[3]).exists()

def test_baseline_without_flows_and_export_metadata(setup):
    client, account, opening, end = setup
    counters(opening)
    assert performance(opening) is None
    assert submit(setup, flow_mode="cumulative", cumulative_start="2026-01-01", cumulative_inflow="112000", cumulative_outflow="2000").status_code == 302
    exported = list(csv.DictReader(io.StringIO(client.get("/export/").content.decode())))
    row = exported[-1]
    assert row["flow_mode"] == "cumulative"
    assert row["cumulative_baseline_date"] == "2026-01-01"
    assert row["cumulative_deposits_eur"] == "112000"
    assert row["deposits_eur"] == ""

def test_imported_tax_basis_and_adjustments_survive(setup):
    client, account, opening, end = setup
    end.imported = True
    end.save()
    TaxAdjustment.objects.create(snapshot=end, kind="broker_vpb", amount_minor=123)
    assert submit(setup, inflow="12000", outflow="2000", basis="90000").status_code == 302
    value = Valuation.objects.get(snapshot=end)
    assert value.basis_minor == 9000000
    assert TaxAdjustment.objects.get(snapshot=end).amount_minor == 123
    assert "Tax basis (EUR)" in client.get(f"/valuations/{end.pk}/").content.decode()

def test_nonpositive_capital_and_unknown_counters(setup):
    client, account, opening, end = setup
    opening.amount_minor = 0
    counters(opening)
    assert submit(setup, flow_mode="cumulative", cumulative_start="2026-01-01", cumulative_inflow="100000", cumulative_outflow="2000").status_code == 302
    value = Valuation.objects.get(snapshot=end)
    assert performance(value)["percent"] is None
    value.cumulative_inflow_minor = None
    assert performance(value) is None


def test_resave_does_not_reinterpret_changed_or_unpublished_baseline(setup):
    client, account, opening, end = setup
    counters(opening)
    fields = dict(flow_mode="cumulative", cumulative_start="2026-01-01", cumulative_inflow="112000", cumulative_outflow="2000")
    assert submit(setup, **fields).status_code == 302
    value = Valuation.objects.get(snapshot=end)
    opening.cumulative_baseline_date = date(2025, 1, 1)
    opening.save()
    assert submit(setup, **fields).status_code == 302
    value.refresh_from_db()
    assert value.cumulative_baseline_date == date(2026, 1, 1)
    assert performance(value) is None
    opening.snapshot.complete = False
    opening.snapshot.save()
    assert submit(setup, **fields).status_code == 302
    value.refresh_from_db()
    assert value.cumulative_start_date == date(2026, 1, 1)
    assert value.cumulative_baseline_date == date(2026, 1, 1)
    assert performance(value) is None


@pytest.mark.django_db(transaction=True)
def test_migration_pins_legacy_flows_without_inventing_unknown_flows():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    old_target = [("wealth", "0003_valuation_interest_minor")]
    new_target = [("wealth", "0004_valuation_cumulative_baseline_date_and_more")]
    executor = MigrationExecutor(connection)
    executor.migrate(old_target)
    try:
        apps = executor.loader.project_state(old_target).apps
        E = apps.get_model("wealth", "Entity")
        A = apps.get_model("wealth", "Account")
        S = apps.get_model("wealth", "Snapshot")
        V = apps.get_model("wealth", "Valuation")
        owner = E.objects.create(name="Migration fictional owner", kind="private")
        account = A.objects.create(name="Migration fictional broker", entity=owner, kind="broker")
        first = S.objects.create(date=date(2026,1,1), complete=True)
        draft = S.objects.create(date=date(2026,2,1))
        end = S.objects.create(date=date(2026,6,1), complete=True)
        unknown = V.objects.create(account=account, snapshot=first, amount_minor=10000)
        V.objects.create(account=account, snapshot=draft, amount_minor=10500)
        known = V.objects.create(account=account, snapshot=end, amount_minor=11800, inflow_minor=1200, outflow_minor=200)
        executor = MigrationExecutor(connection)
        executor.migrate(new_target)
        V = executor.loader.project_state(new_target).apps.get_model("wealth", "Valuation")
        value = V.objects.get(pk=known.pk)
        assert value.flow_start_date == first.date
        assert value.flow_end_date == end.date
        assert value.inflow_minor == 1200 and value.outflow_minor == 200
        value = V.objects.get(pk=unknown.pk)
        assert value.inflow_minor is None and value.flow_start_date is None
    finally:
        MigrationExecutor(connection).migrate(new_target)
