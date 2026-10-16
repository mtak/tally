"""Fictional parser, admin and alternate-write boundary regressions."""
from datetime import date
from types import SimpleNamespace
from django.contrib.auth.models import AnonymousUser
from decimal import Decimal
from importlib import import_module

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory

from tests.test_import_preflight import MODELS, rewrite
from wealth.forms import AccountForm
from wealth.importer import euro, import_overview, parse_overview
from wealth.models import Account, Entity, Snapshot, TaxAdjustment, Valuation
from wealth.validation import MAX_MINOR, MIN_MINOR, to_minor


@pytest.mark.parametrize('text,expected', [
    ('', None), (' \u00a0', None), ('0', 0), ('€ 1.234,56', 123456),
    ('-€ 19', -1900), ('€\u00a0-1,25', -125), ('+12,34', 1234),
    ('0,005', 1), ('-0,005', -1), ('0,0049', 0), ('-0,015', -2),
    ('92.233.720.368.547.758,07', MAX_MINOR), ('-92.233.720.368.547.758,08', MIN_MINOR),
])
def test_dutch_syntax_half_up_and_storage_edges(text, expected):
    assert euro(text) == expected


@pytest.mark.parametrize('text', ['NaN', 'sNaN', 'Infinity', '-Infinity', '1e3',
    '1.23', '12.34.567', '1,234.56', '1 234', '€', '--1', '1€', '€ € 1',
    '1000000000000000000', '92.233.720.368.547.758,075', '-92.233.720.368.547.758,085'])
def test_bad_csv_amounts(text):
    with pytest.raises(ValueError):
        euro(text)


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '1e100', '-1e100'])
def test_nonfinite_and_overflow_conversion(value):
    with pytest.raises(ValidationError):
        to_minor(Decimal(value))


@pytest.mark.django_db
@pytest.mark.parametrize('label,value', [('Example Bank Private Current', '-0,001'),
    ('Hypotheekschuld 1', '0,001'), ('Example Brokerage Corporate Tax', 'NaN'), ('Example Brokerage Contributions', '1.23')])
def test_csv_rejection_has_location_and_no_writes(label, value):
    def change(rows):
        row = next(r for r in rows if len(r) > 1 and r[1] == label)
        row.extend([''] * max(0, 3 - len(row)))
        row[2] = value
    content = rewrite(change)
    before = {m: list(m.objects.values()) for m in MODELS}
    with pytest.raises(ValueError, match=label + r'.*2024-01-01'):
        parse_overview(content)
    assert {m: list(m.objects.values()) for m in MODELS} == before


@pytest.fixture
def portfolio(db):
    owner = Entity.objects.create(name='Fictional person', kind='private')
    account = Account.objects.create(name='Fictional bank', entity=owner)
    snapshot = Snapshot.objects.create(date=date(2026, 1, 1))
    return owner, account, snapshot


def test_account_forms_and_admin_share_rules(portfolio):
    owner, _, _ = portfolio
    company = Entity.objects.create(name='Fictional company', kind='company')
    request = RequestFactory().get('/admin/')
    request.user = AnonymousUser()
    AdminForm = admin.site._registry[Account].get_form(request)
    for Form in (AccountForm, AdminForm):
        payload = {'name': 'Rejected', 'entity': company.pk, 'kind': 'broker',
                   'asset_class': 'equities', 'joint': True, 'currency': 'EUR', 'rate_bps': 0}
        form = Form(data=payload)
        assert not form.is_valid() and 'joint' in form.errors
    for end in ('matures_on', 'closed_on'):
        account = Account(name='Bad dates', entity=owner, started_on=date(2026, 2, 1), **{end: date(2026, 1, 1)})
        with pytest.raises(ValidationError):
            account.save()


def test_direct_and_bulk_writes_reject_atomically(portfolio):
    owner, account, snapshot = portfolio
    first = Valuation.objects.create(account=account, snapshot=snapshot, amount_minor=100)
    other = Account.objects.create(name='Second bank', entity=owner)
    with pytest.raises(ValidationError):
        Valuation.objects.bulk_create([
            Valuation(account=other, snapshot=snapshot, amount_minor=200),
            Valuation(account=account, snapshot=snapshot, amount_minor=-1)])
    assert Valuation.objects.count() == 1
    second = Valuation.objects.create(account=other, snapshot=snapshot, amount_minor=200)
    first.amount_minor = 300
    second.amount_minor = -1
    with pytest.raises(ValidationError):
        Valuation.objects.bulk_update([first, second], ['amount_minor'])
    assert list(Valuation.objects.order_by('pk').values_list('amount_minor', flat=True)) == [100, 200]
    with pytest.raises(ValidationError):
        Valuation.objects.update(amount_minor=-1)
    with pytest.raises(ValidationError):
        account.joint = True
        account.kind = 'broker'
        account.save()


@pytest.mark.parametrize('value', [MAX_MINOR + 1, MIN_MINOR - 1, Decimal('1.5'), float('inf')])
def test_storage_validation_before_integer_coercion(portfolio, value):
    _, account, snapshot = portfolio
    with pytest.raises(ValidationError):
        Valuation.objects.create(account=account, snapshot=snapshot, amount_minor=value)
    assert not Valuation.objects.exists()


def test_signed_fields_and_card_debt_credit_preserved(portfolio):
    _, card, snapshot = portfolio
    card.asset_class = 'credit_card'
    card.save()
    for amount in (-101, 0, 101):
        Valuation.objects.update_or_create(account=card, snapshot=snapshot, defaults={
            'amount_minor': amount, 'net_deposits_minor': -123, 'basis_minor': -456, 'interest_minor': -7})
        assert Valuation.objects.get().amount_minor == amount
    TaxAdjustment.objects.create(snapshot=snapshot, kind='broker_vpb', amount_minor=123)
    with pytest.raises(ValidationError):
        card.asset_class = 'cash'
        Valuation.objects.update(amount_minor=-1)
        card.save()
    card.refresh_from_db()
    assert card.asset_class == 'credit_card'


def test_related_edits_and_partial_writes_cannot_bypass_rules(portfolio):
    owner, account, snapshot = portfolio
    account.joint = True
    account.save()
    owner.kind = 'company'
    with pytest.raises(ValidationError):
        owner.save()
    observation = Valuation.objects.create(account=account, snapshot=snapshot, amount_minor=100)
    account.kind = 'mortgage'
    with pytest.raises(ValidationError):
        account.save()
    # The unsaved account object must not authorize a positive mortgage balance.
    observation.account = account
    observation.amount_minor = -100
    with pytest.raises(ValidationError):
        observation.save(update_fields=['amount_minor'])


def test_tampered_import_rolls_back_late_validation_failure(db):
    from tests.test_tally import fixture_csv
    parsed = parse_overview(fixture_csv())
    parsed['observations'][-1]['amounts']['Example Bank Private Current'] = MAX_MINOR + 1
    with pytest.raises(ValueError):
        import_overview(parsed)
    assert all(not m.objects.exists() for m in MODELS)


def test_compatibility_audit_does_not_repair_history(portfolio):
    from django.apps import apps
    _, account, snapshot = portfolio
    legacy = Valuation(account=account, snapshot=snapshot, amount_minor=-100)
    legacy.save_base(raw=True)
    audit = import_module('wealth.migrations.0008_financial_invariants').audit_financial_records
    with pytest.raises(RuntimeError, match='No records were changed'):
        audit(apps, SimpleNamespace(connection=connection))
    legacy.refresh_from_db()
    assert legacy.amount_minor == -100


def test_admin_signs_and_snapshot_rates(portfolio):
    _, account, snapshot = portfolio
    request = RequestFactory().get('/admin/')
    request.user = AnonymousUser()
    Form = admin.site._registry[Valuation].get_form(request)
    form = Form(data={'account': account.pk, 'snapshot': snapshot.pk,
                      'amount_minor': -1, 'flow_mode': 'period'})
    assert not form.is_valid() and 'amount_minor' in form.errors
    for field in ('ab_bps', 'vpb_bps'):
        with pytest.raises(ValidationError):
            Snapshot.objects.filter(pk=snapshot.pk).update(**{field: 10001})
        with transaction.atomic(), pytest.raises(IntegrityError):
            # Raw SQL demonstrates the constraint independently of ORM validation.
            with connection.cursor() as cursor:
                cursor.execute(f'UPDATE wealth_snapshot SET {field} = 10001 WHERE id = %s', [snapshot.pk])


def test_mortgage_and_signed_optional_values(portfolio):
    _, account, snapshot = portfolio
    account.kind = 'mortgage'
    account.save()
    with pytest.raises(ValidationError):
        Valuation.objects.create(account=account, snapshot=snapshot, amount_minor=1)
    for amount in (MIN_MINOR, 0):
        Valuation.objects.update_or_create(account=account, snapshot=snapshot, defaults={
            'amount_minor': amount, 'net_deposits_minor': -123, 'basis_minor': -456})
    with pytest.raises(ValidationError):
        Valuation.objects.update(inflow_minor=-1)


@pytest.mark.parametrize('language', ['en', 'nl'])
def test_import_web_rejection_is_localized_atomic(db, settings, language):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import Client
    settings.TALLY_AUTH_ENABLED = False
    client = Client()
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
    content = rewrite(lambda rows: rows[3].__setitem__(2, 'NaN'))
    response = client.post('/import/', {'file': SimpleUploadedFile('fictional.csv', content), 'confirm': 'on'})
    assert response.status_code == 200
    html = response.content.decode()
    assert ('Invalid amount in the CSV.' if language == 'en' else 'Ongeldig bedrag in de CSV.') in html
    assert 'Example Bank Private Current' in html and '2024-01-01' in html
    assert all(not m.objects.exists() for m in MODELS)
