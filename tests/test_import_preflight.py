"""Shared preview/apply contract for the supported fictional Overview."""
import csv
import io
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from django.utils import translation

from tests.test_tally import fixture_csv, logged
from wealth.importer import parse_overview, preflight_overview, import_overview
from wealth.models import Account, Entity, ImportRecord, Snapshot, TaxAdjustment, Valuation

pytestmark = pytest.mark.django_db
MODELS = (Entity, Account, Snapshot, Valuation, TaxAdjustment, ImportRecord)


def rewrite(change):
    rows = list(csv.reader(io.StringIO(fixture_csv().decode())))
    change(rows)
    stream = io.StringIO()
    csv.writer(stream).writerows(rows)
    return stream.getvalue().encode()


def assert_blocked(content):
    before = {m: list(m.objects.values()) for m in MODELS}
    parsed = parse_overview(content)
    checked = preflight_overview(parsed)
    assert not checked['compatible'] and checked['errors']
    with pytest.raises(ValueError) as exc:
        import_overview(parsed)
    assert str(exc.value) == '\n'.join(checked['errors'])
    for model, state in before.items():
        assert list(model.objects.values()) == state
    return checked


@pytest.mark.parametrize('mutation', [
    lambda rows: rows.__setitem__(3, ['', 'Renamed bank', '100', '200']),
    lambda rows: rows.__setitem__(8, ['Totaal', '', '', '1593']),
    lambda rows: rows.__setitem__(8, ['Totaal', '', '900', '1593']),
    lambda rows: [r.__setitem__(2, '') for r in rows if len(r) > 2 and r[1] in {'Example Bank Private Current', 'Example Brokerage Value'}],
])
def test_incompatible_files_block_preview_and_apply(mutation):
    assert_blocked(rewrite(mutation))


def test_unrecognized_minimal_file():
    result = assert_blocked(b'Prive,,01-01-2026\n,Renamed bank,100\nTotaal,,100\n')
    assert result['ignored'] == [{'label': 'Renamed bank', 'line': 2}]
    assert result['recognized'] == []


@pytest.mark.parametrize('content', [b'', b'Prive,,\nTotaal,,\n', b'Prive,,01-01-2026\n'])
def test_empty_or_missing_structure(content):
    with pytest.raises(ValueError):
        parse_overview(content)
    assert Snapshot.objects.count() == 0


@pytest.mark.parametrize('field,value', [
    ('started_on', date(2025, 1, 2)), ('closed_on', date(2025, 8, 1)),
    ('asset_class', 'bonds'), ('liquid', False), ('pension', True),
    ('joint', True), ('currency', 'USD'), ('kind', 'claim'),
])
def test_reused_metadata_conflicts(field, value):
    owner = Entity.objects.create(name='Private', kind='private')
    Account.objects.create(name='Example Bank Private Current', entity=owner, **{field: value})
    result = assert_blocked(fixture_csv())
    assert any('Example Bank Private Current' in e for e in result['errors'])


def test_safe_customizations_and_lifecycle_boundaries_preserved():
    owner = Entity.objects.create(name='Private', kind='private')
    account = Account.objects.create(name='Example Bank Private Current', entity=owner,
        started_on=date(2024, 1, 1), closed_on=date(2026, 8, 2),
        matures_on=date(2030, 1, 1), rate_bps=123, notes='Keep this')
    before = Account.objects.values().get(pk=account.pk)
    assert preflight_overview(parse_overview(fixture_csv()))['compatible']
    import_overview(parse_overview(fixture_csv()))
    assert Account.objects.values().get(pk=account.pk) == before


def test_lifecycle_checks_only_actual_observations():
    owner = Entity.objects.create(name='Private', kind='private')
    Account.objects.create(name='Example Bank Private Current', entity=owner, closed_on=date(2025, 8, 1))
    content = rewrite(lambda rows: (rows[3].__setitem__(3, ''), rows[8].__setitem__(3, '1393')))
    assert preflight_overview(parse_overview(content))['compatible']
    import_overview(parse_overview(content))
    assert Valuation.objects.filter(account__name='Example Bank Private Current').count() == 1


def test_parent_conflicts_never_overwritten():
    owner = Entity.objects.create(name='Operating Company', kind='company')
    assert_blocked(fixture_csv())
    owner.refresh_from_db()
    assert owner.parent_id is None


def test_configuration_rechecked_at_apply():
    parsed = parse_overview(fixture_csv())
    assert preflight_overview(parsed)['compatible']
    owner = Entity.objects.create(name='Private', kind='private')
    Account.objects.create(name='Example Bank Private Current', entity=owner, started_on=date(2027, 1, 1))
    with pytest.raises(ValueError):
        import_overview(parsed)
    assert not Snapshot.objects.exists()


def test_rounding_tolerance_zero_blanks_and_optional_rows():
    content = rewrite(lambda rows: (rows[3].__setitem__(2, '0'), rows[8].__setitem__(2, '719')))
    checked = preflight_overview(parse_overview(content))
    assert checked['compatible']
    assert checked['observations'][0]['difference'] == -200
    assert checked['observations'][0]['balance_count'] == 2
    import_overview(checked)
    assert Valuation.objects.get(account__name='Example Bank Private Current', snapshot__date=date(2024, 1, 1)).amount_minor == 0
    assert not Valuation.objects.filter(account__name='Example Deposit Provider').exists()


@pytest.mark.parametrize('lang', ['en', 'nl'])
@pytest.mark.parametrize('confirm', [False, True])
def test_ui_shows_mapping_reconciliation_and_conflicts(logged, lang, confirm):
    logged.cookies['django_language'] = lang
    owner = Entity.objects.create(name='Private', kind='private')
    Account.objects.create(name='Example Bank Private Current', entity=owner, pension=True)
    response = logged.post('/import/', {'file': SimpleUploadedFile('fictional.csv', fixture_csv()),
                                       **({'confirm': 'on'} if confirm else {})})
    assert response.status_code == 200
    preview = response.context['preview']
    assert not preview['compatible']
    assert preview['observations'][1]['source_total'] == 159300
    html = response.content.decode()
    assert 'Example Bank Private Current' in html
    assert ('Per-date reconciliation' if lang == 'en' else 'Aansluiting per datum') in html
    assert not Snapshot.objects.exists()


def test_cli_preview_uses_same_conflicts(tmp_path):
    path = tmp_path / 'fictional.csv'
    path.write_bytes(rewrite(lambda rows: rows[3].__setitem__(1, 'Renamed bank')))
    with translation.override('en'), pytest.raises(CommandError, match='Missing required'):
        call_command('import_overview', str(path), stdout=io.StringIO())
    assert not ImportRecord.objects.exists()


def test_new_consultancy_default_cannot_hide_observations():
    content = rewrite(lambda rows: (next(r for r in rows if len(r) > 1 and r[1] == 'Example Bank Business Current').extend(['0', '']),))
    checked = assert_blocked(content)
    assert any('Example Bank Business Current' in e for e in checked['errors'])


def test_optional_rows_can_be_absent():
    content = rewrite(lambda rows: (rows.__setitem__(slice(5, 8), []),
        next(r for r in rows if r and r[0] == 'Totaal').__setitem__(slice(2, None), ['1100', '2200'])))
    checked = preflight_overview(parse_overview(content))
    assert checked['compatible']
    assert 'Example Brokerage Contributions' in checked['optional_missing']
    import_overview(checked)
    assert set(TaxAdjustment.objects.values_list('amount_minor', flat=True)) == {0}
    assert not Valuation.objects.exclude(basis_minor=None).exists()


def test_late_write_failure_rolls_back_entire_import(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError('fictional write failure')
    monkeypatch.setattr(ImportRecord.objects, 'create', fail)
    with pytest.raises(RuntimeError, match='fictional write failure'):
        import_overview(parse_overview(fixture_csv()))
    for model in MODELS:
        assert not model.objects.exists()


def test_existing_dates_and_files_are_visible_in_preview():
    parsed = parse_overview(fixture_csv())
    import_overview(parsed)
    checked = preflight_overview(parsed)
    assert len(checked['errors']) == 2
    assert not checked['compatible']
