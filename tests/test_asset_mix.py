from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import translation

from wealth.models import Account, Entity, Snapshot, TaxAdjustment, Valuation
from wealth.services import asset_mix, report
from wealth.templatetags.money import percent

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('lang, expected', [('en', '66.67%'), ('nl', '66,67%')])
def test_percentage_display_rounds_without_changing_calculation(lang, expected):
    exact = Decimal(200) / 3
    with translation.override(lang):
        assert percent(exact) == expected
        assert percent(Decimal('12.345')) == ('12,35%' if lang == 'nl' else '12.35%')
    assert exact == Decimal(200) / 3


def setup_portfolio():
    owner = Entity.objects.create(name="Example owner", kind="private")
    cash = Account.objects.create(entity=owner, name="Example cash", asset_class="cash")
    equities = Account.objects.create(entity=owner, name="Example equities", kind="broker", asset_class="equities")
    snapshot = Snapshot.objects.create(date=date(2024, 12, 17), complete=True)
    Valuation.objects.create(account=cash, snapshot=snapshot, amount_minor=3000000)
    Valuation.objects.create(account=equities, snapshot=snapshot, amount_minor=7000000)
    return owner, cash, equities, snapshot


def by_key(mix):
    return {c['key']: c for c in mix['categories']}


def test_exact_gross_mix_independent_of_debts_and_tax():
    owner, cash, equities, snapshot = setup_portfolio()
    mortgage = Account.objects.create(entity=owner, name="Example mortgage", kind="mortgage", asset_class="property")
    Valuation.objects.create(account=mortgage, snapshot=snapshot, amount_minor=-8000000)
    TaxAdjustment.objects.create(snapshot=snapshot, kind="bank_ab", amount_minor=-9999999)
    for net in (True, False):
        categories = by_key(asset_mix(report(snapshot, net=net)))
        assert categories['cash']['percentage'] == Decimal(30)
        assert categories['equities']['percentage'] == Decimal(70)
        assert categories['property']['amount'] == 0
    snapshot.ab_bps = 100
    snapshot.save()
    assert by_key(asset_mix(report(snapshot)))['cash']['percentage'] == 30
    cash.valuations.update(amount_minor=1)
    equities.valuations.update(amount_minor=2)
    mix = asset_mix(report(snapshot))
    assert by_key(mix)['cash']['percentage'] == Decimal(100) / 3
    assert mix['total'] == 3


def test_filters_ownership_unknown_tax_and_zero():
    owner, cash, equities, snapshot = setup_portfolio()
    cash.joint = True
    cash.save()
    equities.pension = True
    equities.save()
    home = Account.objects.create(entity=owner, name="Example home", kind="property", asset_class="property")
    Valuation.objects.create(account=home, snapshot=snapshot, amount_minor=1500000)
    company = Entity.objects.create(name="Example company", kind="company")
    broker = Account.objects.create(entity=company, name="Unknown basis", kind="broker", asset_class="bonds")
    Valuation.objects.create(account=broker, snapshot=snapshot, amount_minor=1000000)
    summary = report(snapshot, include_home=False, include_pension=False)
    assert summary['total'] is None
    mix = asset_mix(summary)
    assert mix['total'] == 2500000
    assert by_key(mix)['cash']['percentage'] == 60
    assert by_key(mix)['bonds']['percentage'] == 40
    assert by_key(mix)['property']['amount'] == by_key(mix)['equities']['amount'] == 0
    Valuation.objects.all().update(amount_minor=0)
    mix = asset_mix(report(snapshot))
    assert mix['total'] == 0
    assert all(c['percentage'] is None for c in mix['categories'])


@pytest.mark.parametrize('lang', ['en', 'nl'])
@pytest.mark.parametrize('cents', [True, False])
def test_annual_selection_dates_carried_observations_and_table(settings, lang, cents):
    settings.TALLY_MONEY_PRECISION = "cents" if cents else "whole"
    owner, cash, equities, old = setup_portfolio()
    earlier = Snapshot.objects.create(date=date(2024, 1, 2), complete=True)
    Snapshot.objects.create(date=date(2025, 6, 1), complete=False)
    latest = Snapshot.objects.create(date=date(2026, 8, 11), complete=True)
    Valuation.objects.create(account=equities, snapshot=latest, amount_minor=7000001)
    Account.objects.create(entity=owner, name="Missing account", asset_class="other")
    client = Client()
    client.force_login(get_user_model().objects.create_user(username='tester'))
    client.cookies['django_language'] = lang
    response = client.get('/')
    assert response.status_code == 200
    assert response.context['chart']['years'] == ['2024', '2026']
    mix = response.context['asset_mix']
    assert [m['snapshot'] for m in mix] == [old, latest]
    cash_category = by_key(mix[-1])['cash']
    assert cash_category['observations'][0]['stale']
    assert cash_category['observations'][0]['valuation'].snapshot == old
    chart = response.context['chart']['mix']
    assert chart['dates'] == ['2024-12-17', '2026-08-11']
    assert chart['series'][0]['data'][-1]['carried_dates'] == ['2024-12-17']
    assert chart['missing'][-1] == ['Missing account']
    html = response.content.decode()
    assert ('Overgenomen' if lang == 'nl' else 'Carried forward') in html
    assert ('Activamixgegevens tonen' if lang == 'nl' else 'Show asset mix data') in html
    expected = ('70.000,01' if lang == 'nl' else '70,000.01') if cents else ('70.000' if lang == 'nl' else '70,000')
    assert expected in html
    assert '<th scope="col"' in html and '<th scope="row"' in html
    response = client.get(f'/?at={earlier.pk}')
    assert response.context['chart']['years'] == ['2024']
    assert all(c['percentage'] is None for c in response.context['asset_mix'][0]['categories'])
