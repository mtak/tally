import csv
import io
from datetime import date
from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from wealth.models import Account, Entity, Snapshot, Valuation, Position, TaxAdjustment
from wealth.services import cumulative_result, performance, movement, report
from wealth.importer import import_overview, parse_overview

pytestmark = pytest.mark.django_db

@pytest.fixture
def setup():
    owner = Entity.objects.create(name="Investor", kind="private")
    account = Account.objects.create(name="Broker", entity=owner, kind="broker", asset_class="equities")
    first = Snapshot.objects.create(date=date(2026, 1, 1), complete=True)
    client = Client()
    user = get_user_model().objects.create_user(username="investor", password="fictional-only")
    client.force_login(user)
    return client, account, first


def submit(client, account, snapshot, amount="118000", net="100000", **extra):
    return client.post(f"/valuations/{snapshot.pk}/", {
        "form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
        "form-0-account_id": str(account.pk), "form-0-amount": amount,
        "form-0-net_deposits": net, "action": "complete", **extra,
    })

@pytest.mark.parametrize("lang", ["en", "nl"])
@pytest.mark.parametrize("amount,net,result", [("118000", "100000", 1800000), ("92000", "100000", -800000), ("0", "0", 0), ("100", "-50", 15000), ("100", "", None)])
def test_first_observation_result(setup, lang, amount, net, result):
    client, account, first = setup
    client.cookies["django_language"] = lang
    assert submit(client, account, first, amount, net).status_code == 302
    value = Valuation.objects.get()
    assert cumulative_result(value) == result
    page = client.get(f"/valuations/{first.pk}/")
    assert page.context["entries"][0]["cumulative_result"] == result
    assert client.get("/analysis/").context["results"][0]["cumulative_result"] == result
    html = page.content.decode()
    assert ("Netto-inleg sinds opening (EUR)" if lang == "nl" else "Net deposits since opening (EUR)") in html
    for old in ('name="form-0-flow_mode"', 'name="form-0-inflow"', 'name="form-0-cumulative_start"', '/positions/'):
        assert old not in html


def test_withdrawals_and_deposits_do_not_change_profit(setup):
    client, account, first = setup
    assert submit(client, account, first).status_code == 302
    for day, amount, net in [(date(2026, 5, 1), "108000", "90000"), (date(2026, 9, 1), "113000", "95000")]:
        snapshot = Snapshot.objects.create(date=day, complete=True)
        assert submit(client, account, snapshot, amount, net).status_code == 302
        value = snapshot.valuations.get()
        assert cumulative_result(value) == 1800000
        assert performance(value)["result"] == 0
        assert movement(snapshot)["parts"][0]["amount"] == 0


def test_unknown_previous_counter_does_not_skip_observation(setup):
    client, account, first = setup
    Valuation.objects.create(account=account, snapshot=first, amount_minor=10000, net_deposits_minor=9000)
    gap = Snapshot.objects.create(date=date(2026, 3, 1), complete=True)
    Valuation.objects.create(account=account, snapshot=gap, amount_minor=11000)
    last = Snapshot.objects.create(date=date(2026, 5, 1), complete=True)
    value = Valuation.objects.create(account=account, snapshot=last, amount_minor=12000, net_deposits_minor=9000)
    assert cumulative_result(value) == 3000
    assert performance(value) is None
    assert movement(last)["parts"][0]["amount"] == 0


def test_precision_export_tax_and_archived_data_survive_edit(setup):
    client, account, first = setup
    account.entity.kind = "company"
    account.entity.save()
    value = Valuation.objects.create(account=account, snapshot=first, amount_minor=1180049,
        net_deposits_minor=1000049, basis_minor=900049, inflow_minor=200, outflow_minor=0)
    position = Position.objects.create(valuation=value, name="Archived", value_minor=2000000, asset_class="bonds")
    tax = TaxAdjustment.objects.create(snapshot=first, kind="broker_vpb", amount_minor=-321)
    assert submit(client, account, first, "11800", "10000", **{"form-0-basis": "9000"}).status_code == 302
    value.refresh_from_db(); tax.refresh_from_db()
    assert (value.amount_minor, value.net_deposits_minor, value.basis_minor) == (1180049, 1000049, 900049)
    assert value.inflow_minor == 200 and value.outflow_minor == 0
    assert tax.amount_minor == -321
    assert report(first)["assets"] == {"equities": 1180049}
    assert not any("Positions" in warning for warning in report(first)["warnings"])
    for path in (f"/positions/{value.pk}/", f"/positions/{value.pk}/edit/{position.pk}/", f"/positions/{position.pk}/delete/"):
        assert client.get(path).status_code == 404
        assert client.post(path).status_code == 404
    assert Position.objects.filter(pk=position.pk).exists()
    row = next(csv.DictReader(io.StringIO(client.get('/export/').content.decode())))
    assert Decimal(row['net_deposits_eur']) == Decimal('10000.49')
    assert submit(client, account, first, "", "").status_code == 200
    assert Position.objects.filter(pk=position.pk).exists()


def test_missing_value_rejects_counter(setup):
    client, account, first = setup
    assert submit(client, account, first, "", "0").status_code == 200
    assert not Valuation.objects.exists()


def test_overview_import_uses_confirmed_example_brokerage_source_without_other_inference():
    from tests.test_tally import fixture_csv
    parsed = parse_overview(fixture_csv())
    import_overview(parsed)
    example_brokerage = Valuation.objects.filter(account__name="Example Brokerage Value").order_by("snapshot__date")
    assert [v.net_deposits_minor for v in example_brokerage] == [90000, 150000]
    assert [cumulative_result(v) for v in example_brokerage] == [10000, 50000]
    assert all(v.net_deposits_minor is None for v in Valuation.objects.exclude(account__name="Example Brokerage Value"))


@pytest.mark.django_db(transaction=True)
def test_migration_backfills_only_known_inception_data_and_preserves_legacy():
    old = [("wealth", "0004_valuation_cumulative_baseline_date_and_more")]
    new = [("wealth", "0005_valuation_net_deposits_minor")]
    executor = MigrationExecutor(connection)
    executor.migrate(old)
    try:
        apps = executor.loader.project_state(old).apps
        E, A, S, V, P, T = [apps.get_model("wealth", name) for name in ("Entity", "Account", "Snapshot", "Valuation", "Position", "TaxAdjustment")]
        owner = E.objects.create(name="Holding", kind="company")
        account = A.objects.create(name="Example Brokerage Value", entity=owner, kind="broker")
        first = S.objects.create(date=date(2025, 1, 1), complete=True, imported=True)
        imported = V.objects.create(account=account, snapshot=first, amount_minor=11800, basis_minor=10000)
        tax = T.objects.create(snapshot=first, kind="broker_vpb", amount_minor=-321)
        position = P.objects.create(valuation=imported, name="Archived", value_minor=100)
        end = S.objects.create(date=date(2026, 1, 1), complete=True)
        other = A.objects.create(name="Other", entity=owner, kind="broker")
        cumulative = V.objects.create(account=account, snapshot=end, amount_minor=11800, flow_mode="cumulative", flow_end_date=end.date, cumulative_inflow_minor=12000, cumulative_outflow_minor=3000, basis_minor=6000)
        period = V.objects.create(account=other, snapshot=end, amount_minor=10000, basis_minor=9000, inflow_minor=100, outflow_minor=0)
        executor = MigrationExecutor(connection); executor.migrate(new)
        apps = executor.loader.project_state(new).apps
        V = apps.get_model("wealth", "Valuation")
        assert V.objects.get(pk=imported.pk).net_deposits_minor == 10000
        migrated = V.objects.get(pk=cumulative.pk)
        assert migrated.net_deposits_minor == 9000 and migrated.basis_minor == 6000
        assert migrated.cumulative_inflow_minor == 12000 and migrated.cumulative_outflow_minor == 3000
        migrated = V.objects.get(pk=period.pk)
        assert migrated.net_deposits_minor is None and migrated.inflow_minor == 100
        assert apps.get_model("wealth", "Position").objects.filter(pk=position.pk).exists()
        assert apps.get_model("wealth", "TaxAdjustment").objects.get(pk=tax.pk).amount_minor == -321
    finally:
        MigrationExecutor(connection).migrate(new)
