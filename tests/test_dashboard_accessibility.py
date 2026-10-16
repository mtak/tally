from datetime import date
import csv
import io
import re

import pytest
from django.utils import translation

from tests.test_tally import logged, owner
from tests.test_editor_conflicts import body
from wealth.forms import AccountForm
from wealth.models import Account, Entity, Snapshot, Valuation
from wealth.services import report, asset_mix
from wealth.preferences import show_cents
from wealth.templatetags.money import money

pytestmark = pytest.mark.django_db


def configured_money(value, cents):
    token = show_cents.set(cents)
    try:
        return money(value)
    finally:
        show_cents.reset(token)


@pytest.mark.parametrize('lang,cents', [('en', '0'), ('nl', '1')])
def test_dashboard_chart_tables_match_reports_and_filters(logged, owner, settings, lang, cents):
    settings.TALLY_MONEY_PRECISION = "cents" if cents == "1" else "whole"
    cash = Account.objects.create(entity=owner, name='Fictional cash', joint=True, asset_class='credit_card')
    home = Account.objects.create(entity=owner, name='Fictional home', kind='property', asset_class='property')
    pension = Account.objects.create(entity=owner, name='Fictional pension', pension=True)
    company = Entity.objects.create(name='Fictional company', kind='company')
    broker = Account.objects.create(entity=company, name='Fictional broker', kind='broker')
    old = Snapshot.objects.create(date=date(2024, 12, 17), complete=True)
    interim = Snapshot.objects.create(date=date(2026, 2, 3), complete=True)
    latest = Snapshot.objects.create(date=date(2026, 8, 11), complete=True)
    Snapshot.objects.create(date=date(2027, 1, 1), complete=False)
    for account, amount in [(cash, -246913), (home, 500001), (pension, 100002)]:
        Valuation.objects.create(account=account, snapshot=old, amount_minor=amount)
    Valuation.objects.create(account=broker, snapshot=latest, amount_minor=300003)
    logged.cookies['django_language'] = lang
    before = list(Valuation.objects.values())
    for query, flags in [('', {}), ('home=0&pension=0&net=0', dict(include_home=False, include_pension=False, net=False))]:
        response = logged.get('/?' + query, HTTP_HX_REQUEST='true')
        chart = response.context['chart']
        reports = [report(snapshot, **flags) for snapshot in (old, latest)]
        assert response.context['wealth_history'] == reports
        assert chart['dates'] == ['2024-12-17', '2026-08-11']
        assert chart['totals'] == [r['total'] for r in reports]
        for index, r in enumerate(reports):
            assert [s['data'][index] for s in chart['series']] == [
                r['groups'][key] / 100 if r['total'] is not None else None
                for key in ('private', 'home', 'business', 'pension')]
        html = response.content.decode()
        table = html.split('id="wealth-data-summary"')[1].split('</table>')[0]
        rows = re.findall(r'<tr><th scope="row">.*?</tr>', table)
        with translation.override(lang):
            for row, r in zip(rows, reports):
                if r['total'] is None:
                    assert 'colspan="5"' in row
                else:
                    assert configured_money(r['total'], cents == '1') in row
                    for amount in r['groups'].values():
                        assert configured_money(amount, cents == '1') in row
            for key, chart_key, summary_id in [('allocation', 'assets', 'allocation-data-summary'), ('liquidity', 'liquidity', 'liquidity-data-summary')]:
                table = html.split('id="' + summary_id + '"')[1].split('</table>')[0]
                for display, point in zip(response.context[key], chart[chart_key]):
                    assert display['name'] == point['name']
                    assert display['amount'] / 100 == point['value']
                    assert configured_money(display['amount'], cents == '1') in table
        assert 'tabindex="0" role="region"' in html
        assert '<caption>' in html and '<th scope="col"' in html
    response = logged.get(f'/?at={interim.pk}')
    assert response.context['chart']['dates'] == ['2024-12-17', '2026-02-03']
    assert list(Valuation.objects.values()) == before


@pytest.mark.parametrize('lang', ['en', 'nl'])
def test_credit_card_entry_history_signed_reporting_and_export(logged, owner, lang):
    logged.cookies['django_language'] = lang
    form = AccountForm(data=dict(name='Fictional card', entity=owner.pk, kind='bank',
                                asset_class='credit_card', liquid=True, currency='EUR'))
    assert form.is_valid(), form.errors
    account = form.save()
    assert account.asset_class == 'credit_card'
    for year, amount in [(2024, -1234), (2025, 0), (2026, 567)]:
        snapshot = Snapshot.objects.create(date=date(year, 8, 11))
        payload = body(logged, snapshot)
        payload['form-0-amount'] = str(amount)
        payload['action'] = 'complete'
        assert logged.post(f'/valuations/{snapshot.pk}/', payload).status_code == 302
        snapshot.refresh_from_db()
        assert snapshot.valuations.get().amount_minor == amount * 100
        summary = report(snapshot)
        assert summary['total'] == summary['liquidity']['liquid'] == amount * 100
        assert asset_mix(summary)['total'] == max(0, amount * 100)
        allocation = logged.get('/').context['chart']['assets']
        assert allocation == ([{'name': 'Creditcard' if lang == 'nl' else 'Credit card', 'value': amount}] if amount > 0 else [])
    label = 'Creditcard' if lang == 'nl' else 'Credit card'
    assert label in logged.get('/accounts/').content.decode()
    editor_html = logged.get(f'/valuations/{snapshot.pk}/').content.decode()
    assert ('negatief saldo' if lang == 'nl' else 'negative balance') in editor_html
    history = logged.get(f'/accounts/{account.pk}/history/')
    assert [v.amount_minor for v in history.context['observations']] == [56700, 0, -123400]
    exported = list(csv.DictReader(io.StringIO(logged.get('/export/').content.decode())))
    assert [r['value_eur'] for r in exported] == ['-1234', '0', '567']
