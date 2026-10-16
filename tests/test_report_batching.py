from datetime import date

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from wealth.models import Account, Entity, Snapshot, TaxAdjustment, Valuation
from wealth.services import report, reports


pytestmark = pytest.mark.django_db


def test_batch_reports_match_individual_reports_and_keep_query_count_bounded():
    company = Entity.objects.create(name="Fictional company", kind="company")
    brokers = [
        Account.objects.create(entity=company, name=f"Fictional broker {index}", kind="broker")
        for index in range(5)
    ]
    snapshots = [
        Snapshot.objects.create(date=date(year, 6, 15), complete=True)
        for year in range(2015, 2027)
    ]
    for index, snapshot in enumerate(snapshots):
        for broker_index, broker in enumerate(brokers):
            if (index + broker_index) % 4 == 0:
                continue
            Valuation.objects.create(
                account=broker,
                snapshot=snapshot,
                amount_minor=(index + 1) * (broker_index + 1) * 100_000,
                basis_minor=(index + 1) * (broker_index + 1) * 80_000,
                net_deposits_minor=(index + 1) * (broker_index + 1) * 75_000,
            )
    TaxAdjustment.objects.create(
        snapshot=snapshots[-1], kind="broker_vpb", amount_minor=-12345
    )

    with CaptureQueriesContext(connection) as short_history:
        short_reports = reports(snapshots[:6])
    with CaptureQueriesContext(connection) as long_history:
        batched = reports(snapshots)

    assert len(short_history) == 3
    assert len(long_history) == 3
    assert len(short_reports) == 6
    assert batched == [report(snapshot) for snapshot in snapshots]
    assert [row["performance"] for row in batched[-1]["rows"]] == [
        row["performance"] for row in report(snapshots[-1])["rows"]
    ]
