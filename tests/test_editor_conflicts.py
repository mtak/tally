from datetime import date
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from wealth.models import Account, Entity, Snapshot, TaxAdjustment, Valuation
from wealth.preferences import cents_cookie_name

pytestmark = pytest.mark.django_db


@pytest.fixture
def editors():
    owner = Entity.objects.create(name="Fictional company", kind="company")
    # Keep broker at row 0 and bank at row 1 under alphabetical ordering.
    broker = Account.objects.create(name="Fictional A broker", entity=owner, kind="broker")
    bank = Account.objects.create(name="Fictional B bank", entity=owner, kind="bank")
    snapshot = Snapshot.objects.create(date=date(2026, 1, 1))
    Valuation.objects.create(snapshot=snapshot, account=broker, amount_minor=10049,
                            net_deposits_minor=8049, basis_minor=9049)
    Valuation.objects.create(snapshot=snapshot, account=bank, amount_minor=20049, interest_minor=149)
    user = get_user_model().objects.create_user(username="editor", password="fictional-only")
    clients = [Client(), Client()]
    for client in clients:
        client.force_login(user)
    return clients, snapshot, broker, bank


def body(client, snapshot):
    response = client.get(f"/valuations/{snapshot.pk}/")
    forms = response.context["formset"]
    data = {"editor_version": response.context["editor_version"],
            "form-TOTAL_FORMS": len(forms), "form-INITIAL_FORMS": len(forms), "action": "draft"}
    for form in forms:
        for name in form.fields:
            value = form[name].value()
            if hasattr(value, "strftime"):
                value = value.strftime("%d-%m-%Y")
            data[f"{form.prefix}-{name}"] = "" if value is None else str(value)
    return data


@pytest.mark.parametrize("lang", ["en", "nl"])
@pytest.mark.parametrize("field,index", [("amount",0), ("basis",0), ("net_deposits",0), ("interest",1)])
def test_old_tab_cannot_overwrite_newer_fields(editors, lang, field, index):
    (a,b), snapshot, broker, bank = editors
    a.cookies["django_language"] = b.cookies["django_language"] = lang
    path = f"/valuations/{snapshot.pk}/"
    stale, newer = body(a,snapshot), body(b,snapshot)
    newer[f"form-{index}-{field}"] = "300"
    if field == "interest":
        newer[f"form-{index}-interest_period_start"] = "01-12-2025"
        newer[f"form-{index}-interest_period_end"] = "01-01-2026"
    response = b.post(path,newer)
    assert response.status_code == 302
    before = list(snapshot.valuations.order_by("pk").values())
    response = a.post(path,stale)
    assert response.status_code == 409
    assert response.context["formset"][index][field].value() == stale[f"form-{index}-{field}"]
    assert response.context["editor_version"] == stale["editor_version"]
    assert list(snapshot.valuations.order_by("pk").values()) == before
    assert ('niet opgeslagen' if lang == 'nl' else 'have not been saved') in response.content.decode()
    assert a.post(path,stale).status_code == 409
    refreshed = body(a,snapshot)
    refreshed["form-0-amount"] = "400"
    assert a.post(path,refreshed).status_code == 302
    assert snapshot.valuations.get(account=broker).amount_minor == 40000


@pytest.mark.parametrize("create", [True,False])
def test_stale_blank_cannot_remove_or_recreate_observation(editors,create):
    (a,b), snapshot, broker, bank = editors
    if create:
        snapshot.valuations.filter(account=bank).delete()
    path = f"/valuations/{snapshot.pk}/"
    stale, newer = body(a,snapshot), body(b,snapshot)
    newer["form-1-amount"] = "500" if create else ""
    newer["form-1-interest"] = ""
    assert b.post(path,newer).status_code == 302
    assert a.post(path,stale).status_code == 409
    assert snapshot.valuations.filter(account=bank).exists() == create


def test_whole_amount_detects_changes_hidden_by_rounding(editors):
    (a,b), snapshot, broker, bank = editors
    path = f"/valuations/{snapshot.pk}/"
    stale = body(a,snapshot)
    b.cookies[cents_cookie_name()] = "1"
    newer = body(b,snapshot)
    newer["form-0-amount"] = "100.40"
    assert b.post(path,newer).status_code == 302
    response = a.post(path,stale)
    assert response.status_code == 409 and '€ 100.40' in response.content.decode()
    assert snapshot.valuations.get(account=broker).amount_minor == 10040


@pytest.mark.parametrize("change", ["publish","delete","account","tax","date"])
def test_changes_outside_observation_inputs(editors,change):
    (a,b), snapshot, broker, bank = editors
    path = f"/valuations/{snapshot.pk}/"
    stale = body(a,snapshot)
    stale["form-0-amount"] = "444"
    if change == "publish":
        newer = body(b,snapshot)
        newer["action"] = "complete"
        assert b.post(path,newer).status_code == 302
    elif change == "delete":
        assert b.post(path+"delete/").status_code == 302
    elif change == "account":
        broker.closed_on = snapshot.date
        broker.save()
    elif change == "tax":
        TaxAdjustment.objects.create(snapshot=snapshot,kind="bank_ab",amount_minor=-123)
    else:
        snapshot.date = date(2026,2,1)
        snapshot.save()
    response = a.post(path,stale)
    assert response.status_code == 409
    assert response.context["formset"][0]["amount"].value() == "444"
    assert response.context["entries"][0]["account"].name == broker.name
    if change == "delete":
        assert response.context["deleted"]
        assert not Snapshot.objects.exists() and not Valuation.objects.exists()
        assert a.get(path).status_code == 404
    else:
        assert snapshot.valuations.get(account=broker).amount_minor == 10049
        if change == "publish":
            snapshot.refresh_from_db()
            assert snapshot.complete


@pytest.mark.parametrize("token", ["","forged","other-snapshot"])
def test_invalid_tokens_do_not_write(editors,token):
    (a,b), snapshot, broker, bank = editors
    data = body(a,snapshot)
    if token == "other-snapshot":
        other = Snapshot.objects.create(date=date(2026,2,1))
        token = body(a,other)["editor_version"]
    data["editor_version"] = token
    data["form-0-amount"] = "999"
    assert a.post(f"/valuations/{snapshot.pk}/",data).status_code == 409
    assert snapshot.valuations.get(account=broker).amount_minor == 10049


def test_invalid_input_retry_keeps_original_revision(editors):
    (a,b), snapshot, broker, bank = editors
    path = f"/valuations/{snapshot.pk}/"
    data = body(a,snapshot)
    data["form-0-amount"] = "invalid"
    response = a.post(path,data)
    assert response.status_code == 200
    assert response.context["editor_version"] == data["editor_version"]
    newer = body(b,snapshot)
    newer["form-0-amount"] = "333"
    assert b.post(path,newer).status_code == 302
    data["form-0-amount"] = "444"
    assert a.post(path,data).status_code == 409
    assert snapshot.valuations.get(account=broker).amount_minor == 33300


@pytest.mark.parametrize("lang", ["en", "nl"])
@pytest.mark.parametrize("malformed", ["duplicate", "foreign", "order", "missing-id", "count", "management", "action"])
@pytest.mark.parametrize("stale", [False, True])
def test_malformed_editor_uses_translated_safe_page(editors, lang, malformed, stale):
    (client, _), snapshot, broker, bank = editors
    client.cookies['django_language'] = lang
    data = body(client, snapshot)
    data['form-0-amount'] = '987654321'
    if malformed == 'duplicate':
        data['form-1-account_id'] = data['form-0-account_id']
    elif malformed == 'foreign':
        data['form-0-account_id'] = '999999'
    elif malformed == 'order':
        data['form-0-account_id'], data['form-1-account_id'] = data['form-1-account_id'], data['form-0-account_id']
    elif malformed == 'missing-id':
        del data['form-0-account_id']
    elif malformed == 'count':
        data['form-TOTAL_FORMS'] = '1'
    elif malformed == 'management':
        del data['form-TOTAL_FORMS']
    else:
        data['action'] = 'unknown'
    if stale:
        broker.name = 'Renamed broker'
        broker.save()
    before = list(snapshot.valuations.values())
    response = client.post(f'/valuations/{snapshot.pk}/', data)
    assert response.status_code == 400
    assert response.templates[0].name == 'wealth/snapshot_edit.html'
    html = response.content.decode()
    expected = ('Ongeldige' if lang == 'nl' else 'Invalid')
    assert expected in response.context['editor_error']
    assert 'role="alert"' in html
    assert response.context['editor_version'] == data['editor_version']
    assert list(snapshot.valuations.values()) == before
    if malformed != 'action':
        assert '987654321' not in html
        assert response.context['unsafe_layout']
        assert response.context['entries'][0]['form']['account_id'].value() == broker.pk
    else:
        assert response.context['formset'][0]['amount'].value() == '987654321'
    snapshot.refresh_from_db()
    assert not snapshot.complete
