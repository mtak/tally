import pytest

from tests.test_tally import account, logged, owner, snap
from wealth.models import Account, Entity, TaxAdjustment, Valuation
from wealth.services import report

pytestmark = pytest.mark.django_db


def data(account, **changes):
    return {"name": account.name, "entity": account.entity_id, "kind": "bank",
            "asset_class": "cash", "currency": "EUR", "liquid": "on", **changes}


@pytest.mark.parametrize("changes,impact", [
    ({"joint": "on"}, "Joint ownership"),
    ({"kind": "broker"}, "Account type"),
    ({"asset_class": "equities"}, "Asset class"),
    ({"liquid": ""}, "Liquid:"),
    ({"pension": "on"}, "Pension:"),
    ({"started_on": "01-02-2026"}, "Start date"),
    ({"closed_on": "01-01-2026"}, "Closed on"),
    ({"matures_on": "01-02-2026"}, "Maturity date"),
    ({"entity": "company"}, "Owner:"),
])
def test_history_changes_require_review(logged, account, snap, changes, impact):
    Valuation.objects.create(account=account, snapshot=snap, amount_minor=10001)
    if changes.get("entity") == "company":
        changes = {"entity": Entity.objects.create(name="Fictional company", kind="company").pk}
    before = Account.objects.values().get(pk=account.pk)
    url = f"/accounts/{account.pk}/"
    response = logged.post(url, data(account, **changes))
    assert response.status_code == 200
    assert any(impact in text for text in response.context["history_impacts"])
    assert Account.objects.values().get(pk=account.pk) == before
    token = response.context["history_confirmation"]
    assert token
    assert logged.post(url, data(account, **changes, history_confirmation=token)).status_code == 302
    assert Valuation.objects.get(account=account).amount_minor == 10001


@pytest.mark.parametrize("language", ["en", "nl"])
def test_confirmed_joint_change_reinterprets_history_without_rewriting(logged, account, snap, language):
    logged.cookies["django_language"] = language
    Valuation.objects.create(account=account, snapshot=snap, amount_minor=10000)
    TaxAdjustment.objects.create(snapshot=snap, kind="bank_ab", amount_minor=-123)
    before = list(Valuation.objects.values()), list(TaxAdjustment.objects.values())
    url = f"/accounts/{account.pk}/"
    response = logged.post(url, data(account, joint="on"))
    assert ("Review impact" if language == "en" else "Controleer de gevolgen") in response.content.decode()
    assert report(snap)["groups"]["private"] == 10000
    token = response.context["history_confirmation"]
    assert logged.post(url, data(account, joint="on", history_confirmation=token)).status_code == 302
    assert report(snap)["groups"]["private"] == 5000
    assert (list(Valuation.objects.values()), list(TaxAdjustment.objects.values())) == before


def test_confirmation_rejects_modified_values_concurrent_changes_and_invalid_form(logged, account, snap):
    Valuation.objects.create(account=account, snapshot=snap, amount_minor=10000)
    url = f"/accounts/{account.pk}/"
    token = logged.post(url, data(account, joint="on")).context["history_confirmation"]
    for submitted in (data(account, joint="on", pension="on"), data(account, joint="on", currency="invalid")):
        assert logged.post(url, {**submitted, "history_confirmation": token}).status_code == 200
        account.refresh_from_db()
        assert not account.joint
    Account.objects.filter(pk=account.pk).update(notes="Another editor")
    response = logged.post(url, data(account, joint="on", history_confirmation=token))
    assert response.status_code == 200 and response.context["history_confirmation"] != token
    account.refresh_from_db()
    assert not account.joint and account.notes == "Another editor"
    assert logged.post(url, data(account, joint="on", history_confirmation="forged")).status_code == 200


def test_harmless_and_unpublished_changes_save_normally(logged, account, snap):
    url = f"/accounts/{account.pk}/"
    assert logged.post(url, data(account, joint="on")).status_code == 302
    Valuation.objects.create(account=account, snapshot=snap, amount_minor=10000)
    assert logged.post(url, data(account, joint="on", name="Renamed", notes="Fictional note", interest_rate="2")).status_code == 302


def test_rejected_valuation_inputs_remain_guarded_until_save(logged, account, snap):
    Valuation.objects.create(account=account, snapshot=snap, amount_minor=10001)
    url = f"/valuations/{snap.pk}/"
    page = logged.get(url)
    assert b'data-unsaved="false"' in page.content
    payload = {"editor_version": page.context["editor_version"], "form-TOTAL_FORMS": "1",
               "form-INITIAL_FORMS": "1", "form-0-account_id": account.pk,
               "form-0-amount": "invalid", "action": "complete"}
    rejected = logged.post(url, payload)
    assert b'data-unsaved="true"' in rejected.content
    assert b'value="invalid"' in rejected.content
    payload["form-0-amount"] = "100"
    saved = logged.post(url, payload, follow=True)
    assert b'data-unsaved="false"' in saved.content
    assert Valuation.objects.get(account=account).amount_minor == 10001
