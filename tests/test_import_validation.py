"""Small fictional Overview inputs, each isolating one ambiguity/conflict."""
import csv
import io

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import translation

from wealth.importer import parse_overview, import_overview
from wealth.models import Account, Entity, ImportRecord, Snapshot, TaxAdjustment, Valuation

pytestmark = pytest.mark.django_db


def overview(extra=()):
    rows = [
        ["Prive", "", "01-01-2024"],
        ["", "Example Bank Private Current", "100"],
        ["", "Example Brokerage Contributions", "90"],
        ["", "Example Bank Capital Tax", "-1"],
        ["", "Example Brokerage Corporate Tax", "-2"],
        ["", "Example Brokerage Capital Tax", "-3"],
        ["", "Liquide vermogen", "100"],
        ["", "Niet-liquide vermogen", "0"],
        ["Totaal", "", "94"],
        *extra,
    ]
    from wealth.importer import MAPPING
    present = {row[1].strip() for row in rows if len(row) > 1}
    rows.extend(["", m[0]] for m in MAPPING if m[0] not in present)
    stream = io.StringIO()
    csv.writer(stream).writerows(rows)
    return stream.getvalue().encode()


@pytest.mark.parametrize("lang", ["en", "nl"])
@pytest.mark.parametrize("row,first", [
    (["", "Example Bank Private Current", "100"], 2),  # identical account
    (["", " Example Bank Private Current ", "999"], 2),  # conflicting account
    (["", "Example Brokerage Contributions", "999"], 3),
    (["", "Example Bank Capital Tax", "-9"], 4),
    (["", "Example Brokerage Corporate Tax", "-9"], 5),
    (["", "Example Brokerage Capital Tax", "-9"], 6),
    (["", "Liquide vermogen", "999"], 7),
    (["", "Niet-liquide vermogen", "999"], 8),
    (["Prive", "", "02-01-2025"], 1),
    (["Totaal", "", "999"], 9),
])
def test_duplicate_consumed_rows_rejected_atomically(lang, row, first):
    with translation.override(lang), pytest.raises(ValueError) as exc:
        import_overview(parse_overview(overview([row])))
    message = str(exc.value)
    assert ('Dubbele CSV-rij' if lang == 'nl' else 'Duplicate CSV row') in message
    assert (row[1].strip() or row[0]) in message
    assert f'{first}' in message and '10' in message
    for model in (Entity, Account, Snapshot, Valuation, TaxAdjustment, ImportRecord):
        assert model.objects.count() == 0


def test_repeated_irrelevant_headings_remain_supported():
    extra = [["", "Totaal banktegoeden", "999"], ["Zakelijk", "Section", ""]] * 2
    assert import_overview(parse_overview(overview(extra))) == 1
    assert Valuation.objects.get().amount_minor == 10000


@pytest.mark.parametrize("lang", ["en", "nl"])
@pytest.mark.parametrize("conflict", ["owner", "account"])
def test_import_configuration_conflicts_in_normal_ui_are_atomic(lang, conflict):
    owner = Entity.objects.create(name='Operating Company' if conflict == 'owner' else 'Other <owner>', kind='private')
    if conflict == 'account':
        Account.objects.create(name='Example Bank Private Current', entity=owner)
    before = {model: list(model.objects.values()) for model in
              (Entity, Account, Snapshot, Valuation, TaxAdjustment, ImportRecord)}
    client = Client()
    client.force_login(get_user_model().objects.create_user(username='importer'))
    client.cookies['django_language'] = lang
    response = client.post('/import/', {'file': SimpleUploadedFile('fictional.csv', overview()), 'confirm': 'on'})
    assert response.status_code == 200
    assert response.templates[0].name == 'wealth/import.html'
    message = str(response.context['form'].non_field_errors())
    if lang == 'nl':
        assert ('Eigenaarconfiguratie' if conflict == 'owner' else 'Rekeningconfiguratie') in message
    else:
        assert ('Owner configuration' if conflict == 'owner' else 'Account configuration') in message
    assert ('Operating Company' if conflict == 'owner' else 'Example Bank Private Current') in message
    for model, state in before.items():
        assert list(model.objects.values()) == state
