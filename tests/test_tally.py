import csv, io
from datetime import date
from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.utils import translation
from wealth.models import (
    Entity,
    Account,
    Snapshot,
    Valuation,
    Position,
    TaxAdjustment,
    ImportRecord,
)
from wealth.services import report, performance, rate
from wealth.importer import parse_overview, import_overview
from wealth.forms import AccountForm, ValuationForm

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return Entity.objects.create(name="Test person", kind="private")


@pytest.fixture
def account(owner):
    return Account.objects.create(name="Test account", entity=owner)


@pytest.fixture
def snap():
    return Snapshot.objects.create(date=date(2026, 1, 1), complete=True)


@pytest.fixture
def logged():
    client = Client()
    u = get_user_model().objects.create_user(
        username="tester", password="fictional-test-only"
    )
    client.force_login(u)
    return client


def test_joint_ownership_is_applied_once(account, snap):
    account.joint = True
    account.save()
    Valuation.objects.create(snapshot=snap, account=account, amount_minor=10001)
    r = report(snap)
    assert r["total"] == 5001
    assert sum(r["assets"].values()) == 5001


def test_unknown_and_zero_are_distinct(account, snap):
    assert report(snap)["missing"] == [account.name]
    Valuation.objects.create(snapshot=snap, account=account, amount_minor=0)
    assert report(snap)["missing"] == []


def test_carry_forward_retains_date_and_excludes_other_drafts(account, snap):
    old = Valuation.objects.create(snapshot=snap, account=account, amount_minor=10000)
    draft = Snapshot.objects.create(date=date(2026, 2, 1))
    Valuation.objects.create(snapshot=draft, account=account, amount_minor=99999)
    later = Snapshot.objects.create(date=date(2026, 3, 1), complete=True)
    r = report(later)
    assert r["total"] == 10000 and r["rows"][0]["valuation"].snapshot.date == snap.date
    assert account.name in r["stale"]


def test_future_values_and_closed_accounts_not_carried_back(account, snap):
    account.closed_on = date(2026, 2, 1)
    account.save()
    Valuation.objects.create(snapshot=snap, account=account, amount_minor=100)
    later = Snapshot.objects.create(date=date(2026, 2, 1), complete=True)
    assert report(snap)["total"] == 100 and report(later)["total"] == 0


def test_start_date_hides_unopened_accounts(account, snap):
    account.started_on = date(2026, 2, 1)
    account.save()
    assert report(snap)["missing"] == []


def test_home_pension_filters_and_gross_allocation(owner, snap):
    for name, kind, pension, value in [
        ("Home", "property", False, 50000000),
        ("Debt", "mortgage", False, -30000000),
        ("Pension", "broker", True, 4000000),
    ]:
        a = Account.objects.create(
            name=name,
            kind=kind,
            pension=pension,
            entity=owner,
            liquid=False,
            asset_class="property" if not pension else "equities",
        )
        Valuation.objects.create(account=a, snapshot=snap, amount_minor=value)
    assert report(snap)["total"] == 24000000
    assert sum(report(snap)["assets"].values()) == 54000000
    assert report(snap, include_home=False)["total"] == 4000000
    assert report(snap, include_pension=False)["total"] == 20000000


def test_company_tax_loss_credit_and_historical_override(snap):
    e = Entity.objects.create(name="Holding", kind="company")
    a = Account.objects.create(name="Company broker", entity=e, kind="broker")
    Valuation.objects.create(
        account=a, snapshot=snap, amount_minor=9000000, basis_minor=10000000
    )
    r = report(snap)
    assert r["tax"]["broker_vpb"] == 190000
    assert r["tax"]["broker_ab"] == -2472110
    assert r["total"] == 9000000 + 190000 - 2472110
    TaxAdjustment.objects.create(snapshot=snap, kind="broker_vpb", amount_minor=123)
    assert report(snap)["tax"]["broker_vpb"] == 123
    assert report(snap, net=False)["total"] == 9000000


def test_sole_proprietor_is_not_box_two(snap):
    e = Entity.objects.create(name="Sole", kind="sole")
    a = Account.objects.create(name="Sole cash", entity=e)
    Valuation.objects.create(snapshot=snap, account=a, amount_minor=50000)
    assert report(snap)["groups"]["business"] == 50000
    assert report(snap)["tax_total"] == 0 and report(snap)["boxes"]["2"] == 0


def test_account_return_uses_flows_not_trades(account, snap):
    Valuation.objects.create(account=account, snapshot=snap, amount_minor=10000000, net_deposits_minor=10000000)
    s = Snapshot.objects.create(date=date(2025, 8, 1), complete=True)
    v = Valuation.objects.create(
        account=account,
        snapshot=s,
        amount_minor=11800000,
        flow_start_date=snap.date,
        flow_end_date=s.date,
        net_deposits_minor=11000000,
        inflow_minor=1200000,
        outflow_minor=200000,
    )
    result = performance(v)
    assert result["result"] == 800000
    assert result["net_deposits"] == 1000000
    v.net_deposits_minor = None
    assert performance(v) is None


def test_positions_do_not_double_count(account, snap):
    v = Valuation.objects.create(account=account, snapshot=snap, amount_minor=10000)
    Position.objects.create(
        valuation=v, name="Equity", asset_class="equities", value_minor=7500
    )
    r = report(snap)
    assert r["total"] == 10000 and r["assets"] == {account.asset_class: 10000}
    Position.objects.create(
        valuation=v, name="Excess", asset_class="cash", value_minor=5000
    )
    assert not report(snap)["warnings"]


def fixture_csv():
    rows = [
        ["", "", ""],
        ["", "", ""],
        ["Prive", "", "01-01-2024", "€ 12.345"],
        ["", "Example Bank Private Current", "€ 100", "€ 200"],
        ["", "Example Brokerage Value", "€ 1.000", "€ 2.000"],
        ["", "Example Brokerage Contributions", "€ 900", "€ 1.500"],
        ["", "Example Brokerage Corporate Tax", "-€ 19", "-€ 95"],
        ["", "Example Brokerage Capital Tax", "-€ 264", "-€ 512"],
        ["Totaal", "", "€ 817", "€ 1.593"],
        ["", "Liquide vermogen", "€ 100", ""],
        ["", "Niet-liquide vermogen", "€ 0", ""],
    ]
    from wealth.importer import MAPPING
    present = {row[1].strip() for row in rows if len(row) > 1}
    rows.extend(["", m[0]] for m in MAPPING if m[0] not in present)
    f = io.StringIO()
    csv.writer(f).writerows(rows)
    return f.getvalue().encode()


def test_csv_import_dates_roundtrip_and_duplicate_protection():
    p = parse_overview(fixture_csv())
    assert p["observations"][-1]["date"] == date(2025, 8, 1)
    assert import_overview(p) == 2
    assert Account.objects.get(name="Gezamenlijke rekening").joint
    latest = Snapshot.objects.latest("date")
    assert report(latest)["total"] == 159300
    assert report(latest)["source_difference"] == 0
    with pytest.raises(ValueError):
        import_overview(p)
    assert Snapshot.objects.count() == 2


def test_overlapping_import_is_atomic(snap):
    p = parse_overview(fixture_csv())
    p["observations"][0]["date"] = snap.date
    with pytest.raises(ValueError):
        import_overview(p)
    assert Account.objects.count() == 0 and ImportRecord.objects.count() == 0


@pytest.mark.parametrize(
    "url", ["/", "/accounts/", "/valuations/", "/analysis/", "/export/", "/import/"]
)
def test_login_required(url):
    assert Client().get(url).status_code == 302


@pytest.mark.parametrize("lang", ["nl", "en"])
def test_render_all_screens_in_both_languages(logged, lang):
    call_command("seed_demo")
    logged.cookies["django_language"] = lang
    s = Snapshot.objects.latest("date")
    v = Valuation.objects.filter(account__kind="broker").first()
    for path in [
        "/",
        "/accounts/",
        "/accounts/new/",
        "/owners/new/",
        "/valuations/",
        "/valuations/new/",
        f"/valuations/{s.pk}/",
        "/analysis/",
        "/import/",
    ]:
        assert logged.get(path).status_code == 200, path
    expected = (
        "Je vermogen in één oogopslag" if lang == "nl" else "Your wealth at a glance"
    )
    assert expected in logged.get("/").content.decode()


def test_nl_input_and_missing_value_validation():
    with translation.override("nl"):
        f = ValuationForm(
            {"account_id": 1, "amount": "1234,56", "net_deposits": "-100,25"}, show_cents=True
        )
        assert f.is_valid(), f.errors
        assert f.cleaned_data["amount"] == Decimal("1234.56")
        f = ValuationForm(
            {"account_id": 1, "amount": "", "net_deposits": "0"}
        )
        assert not f.is_valid()


def test_snapshot_save_rejects_negative_assets(logged, account, snap):
    body = {
        "form-TOTAL_FORMS": "1",
        "form-INITIAL_FORMS": "1",
        "form-0-account_id": str(account.pk),
        "form-0-amount": "-100",
        "action": "complete",
    }
    body["editor_version"] = logged.get(f"/valuations/{snap.pk}/").context["editor_version"]
    response = logged.post(f"/valuations/{snap.pk}/", body)
    assert response.status_code == 200 and not Valuation.objects.exists()


def test_snapshot_saves_zero_and_publishes(logged, account, snap):
    body = {
        "form-TOTAL_FORMS": "1",
        "form-INITIAL_FORMS": "1",
        "form-0-account_id": str(account.pk),
        "form-0-amount": "0",
        "action": "complete",
    }
    body["editor_version"] = logged.get(f"/valuations/{snap.pk}/").context["editor_version"]
    assert logged.post(f"/valuations/{snap.pk}/", body).status_code == 302
    assert Valuation.objects.get().amount_minor == 0


def test_position_deletion_requires_post_and_auth(logged, account, snap):
    v = Valuation.objects.create(account=account, snapshot=snap, amount_minor=100)
    p = Position.objects.create(valuation=v, name="Test", value_minor=100)
    assert logged.get(f"/positions/{p.pk}/delete/").status_code == 404
    assert Position.objects.filter(pk=p.pk).exists()


def test_rounding_half_up(account, snap):
    Valuation.objects.create(account=account, snapshot=snap, amount_minor=100)
    # pytest's in-memory SQLite connection cannot be reopened by filename.
    # File-backed backup/restore is covered by test_backup.py and production_smoke.py.
    from wealth.services import rounded

    assert rounded(Decimal("0.5")) == 1 and rounded(Decimal("-0.5")) == -1


def test_movement_bridge_reconciles_and_ignores_internal_flows(owner, snap):
    from wealth.services import movement

    cash = Account.objects.create(name="Cash", entity=owner)
    broker = Account.objects.create(name="Broker", entity=owner, kind="broker")
    Valuation.objects.create(account=cash, snapshot=snap, amount_minor=20000)
    Valuation.objects.create(account=broker, snapshot=snap, amount_minor=10000, net_deposits_minor=10000)
    later = Snapshot.objects.create(date=date(2026, 5, 1), complete=True)
    Valuation.objects.create(
        account=cash, snapshot=later, amount_minor=15100, interest_minor=100
    )
    Valuation.objects.create(
        account=broker,
        snapshot=later,
        amount_minor=17000,
        flow_start_date=snap.date,
        flow_end_date=later.date,
        net_deposits_minor=15000,
        inflow_minor=5000,
        outflow_minor=0,
    )
    bridge = movement(later)
    assert bridge["closing"] == 32100
    assert [p["amount"] for p in bridge["parts"]] == [2000, 100, 0, 0, 0]
    assert (
        bridge["opening"] + sum(p["amount"] for p in bridge["parts"])
        == bridge["closing"]
    )


@pytest.mark.parametrize("language", ["en", "nl"])
def test_analysis_chart_excludes_wealth_totals_and_tracks_period(logged, account, snap, language):
    import json
    import re
    from wealth.templatetags.money import money

    Valuation.objects.create(account=account, snapshot=snap, amount_minor=100000000)
    later = Snapshot.objects.create(date=date(2026, 5, 1), complete=True)
    Valuation.objects.create(account=account, snapshot=later,
                            amount_minor=100010000, interest_minor=20000)
    latest = Snapshot.objects.create(date=date(2026, 9, 1), complete=True)
    Valuation.objects.create(account=account, snapshot=latest,
                            amount_minor=100005000, interest_minor=0)
    with translation.override(language):
        for selected, opening, closing, values in [
            (later, 100000000, 100010000, [0, 200, 0, 0, -100]),
            (latest, 100010000, 100005000, [0, 0, 0, 0, -50]),
        ]:
            response = logged.get("/analysis/", {"at": selected.pk})
            assert response.status_code == 200
            html = response.content.decode()
            chart = json.loads(re.search(
                r'<script id="movement-data" type="application/json">(.*?)</script>', html
            ).group(1))
            assert chart["values"] == values
            assert len(chart["labels"]) == 5
            assert money(opening) in html
            assert money(closing) in html
            assert response.context["movement"]["after"] == selected


def test_company_account_requires_basis_when_publishing(logged, snap):
    entity = Entity.objects.create(name="Example company", kind="company")
    account = Account.objects.create(
        name="Company investments", entity=entity, kind="broker"
    )
    payload = {
        "form-TOTAL_FORMS": "1",
        "form-INITIAL_FORMS": "1",
        "form-0-account_id": str(account.pk),
        "form-0-amount": "1000",
        "action": "complete",
    }
    payload["editor_version"] = logged.get(f"/valuations/{snap.pk}/").context["editor_version"]
    response = logged.post(f"/valuations/{snap.pk}/", payload)
    assert response.status_code == 200
    assert not Valuation.objects.exists()
    payload["form-0-basis"] = "900"
    assert logged.post(f"/valuations/{snap.pk}/", payload).status_code == 302
    assert Valuation.objects.get().basis_minor == 90000


@pytest.mark.parametrize("saved", [None, "unsupported", ""])
def test_first_visit_uses_english_despite_dutch_browser(logged, saved):
    if saved is not None:
        logged.cookies["django_language"] = saved
    for path in ["/login/", "/", "/accounts/new/", "/analysis/"]:
        response = logged.get(path, HTTP_ACCEPT_LANGUAGE="nl-NL,nl;q=0.9,en;q=0.8")
        assert response.status_code == 200
        assert response.headers["Content-Language"] == "en"
        assert '<html lang="en" data-theme="dark"' in response.content.decode()


@pytest.mark.parametrize("language", ["nl", "en"])
def test_explicit_language_selection_persists(logged, language):
    response = logged.post("/language/setlang/", {"language": language, "next": "/"})
    assert response.status_code == 302
    assert response.cookies["django_language"].value == language
    for path in ["/login/", "/", "/accounts/new/", "/analysis/"]:
        response = logged.get(path, HTTP_ACCEPT_LANGUAGE="en" if language == "nl" else "nl")
        assert response.headers["Content-Language"] == language
        assert f'<html lang="{language}"' in response.content.decode()
        assert "Cookie" in response.headers["Vary"]


@pytest.mark.parametrize("lang, expected", [("en", "€ 1,235"), ("nl", "€ 1.235")])
def test_whole_amount_display_and_preference(logged, account, snap, lang, expected):
    from wealth.preferences import cents_cookie_name
    Valuation.objects.create(account=account, snapshot=snap, amount_minor=123456)
    logged.cookies["django_language"] = lang
    page = logged.get("/").content.decode()
    assert expected in page
    assert 'data-show-cents="false"' in page
    response = logged.post("/preferences/money/", {"show_cents": "1", "next": "/?home=0"})
    assert response.url == "/?home=0"
    assert response.cookies[cents_cookie_name()]["max-age"] == 31536000
    page = logged.get("/").content.decode()
    assert ('€ 1.234,56' if lang == 'nl' else '€ 1,234.56') in page
    assert 'data-show-cents="true"' in page
    assert logged.post("/preferences/money/", {"next": "https://example.com"}).url == "/"
    assert logged.get("/preferences/money/").status_code == 405


@pytest.mark.parametrize("lang, amount", [("en", "123.45"), ("nl", "123,45")])
def test_whole_money_input_rejects_fraction(lang, amount):
    with translation.override(lang):
        form = ValuationForm({"account_id": 1, "amount": amount})
        assert not form.is_valid()
        assert "amount" in form.errors
        enabled = ValuationForm({"account_id": 1, "amount": amount}, show_cents=True)
        assert enabled.is_valid(), enabled.errors


def test_rounded_valuation_save_preserves_cents(logged, account, snap):
    v = Valuation.objects.create(account=account, snapshot=snap, amount_minor=123456,
                                basis_minor=120049, interest_minor=155)
    path = f"/valuations/{snap.pk}/"
    html = logged.get(path).content.decode()
    assert 'value="1235"' in html
    data = {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
            "form-0-account_id": account.pk, "form-0-amount": "1235",
            "form-0-basis": "1200", "form-0-interest": "2", "action": "complete"}
    data["editor_version"] = logged.get(path).context["editor_version"]
    assert logged.post(path, data).status_code == 302
    v.refresh_from_db()
    assert (v.amount_minor, v.basis_minor, v.interest_minor) == (123456, 120049, 155)
    data["form-0-amount"] = "1236"
    data["editor_version"] = logged.get(path).context["editor_version"]
    assert logged.post(path, data).status_code == 302
    v.refresh_from_db()
    assert v.amount_minor == 123600


@pytest.fixture
def draft(account):
    snapshot = Snapshot.objects.create(date=date(2026, 2, 1))
    observation = Valuation.objects.create(snapshot=snapshot, account=account, amount_minor=12345)
    Position.objects.create(valuation=observation, name="Fictional position", value_minor=12345)
    TaxAdjustment.objects.create(snapshot=snapshot, kind="bank_ab", amount_minor=-100)
    return snapshot


@pytest.mark.parametrize("lang", ["en", "nl"])
def test_draft_delete_confirmation_and_cancellation(logged, draft, lang):
    logged.cookies["django_language"] = lang
    path = f"/valuations/{draft.pk}/delete/"
    response = logged.get(path)
    assert response.status_code == 200
    text = response.content.decode()
    assert ("Concept verwijderen?" if lang == "nl" else "Delete draft?") in text
    assert ("waarnemingen, posities en belastingcorrecties" if lang == "nl" else "observations, positions and tax adjustments") in text
    assert 'name="csrfmiddlewaretoken"' in text
    assert f'href="/valuations/{draft.pk}/"' in text
    assert logged.get(f"/valuations/{draft.pk}/").status_code == 200
    assert Snapshot.objects.filter(pk=draft.pk).exists()
    assert draft.valuations.count() == 1
    assert Position.objects.count() == 1
    assert draft.tax_adjustments.count() == 1
    for page in ["/valuations/", f"/valuations/{draft.pk}/"]:
        assert path in logged.get(page).content.decode()


@pytest.mark.parametrize("lang", ["en", "nl"])
def test_draft_delete_removes_related_records_only(logged, draft, account, snap, lang):
    published = Valuation.objects.create(snapshot=snap, account=account, amount_minor=54321)
    logged.cookies["django_language"] = lang
    response = logged.post(f"/valuations/{draft.pk}/delete/", follow=True)
    assert response.redirect_chain == [("/valuations/", 302)]
    assert ("Concept verwijderd." if lang == "nl" else "Draft deleted.") in response.content.decode()
    assert not Snapshot.objects.filter(pk=draft.pk).exists()
    assert not Valuation.objects.filter(snapshot_id=draft.pk).exists()
    assert not Position.objects.exists()
    assert not TaxAdjustment.objects.filter(snapshot_id=draft.pk).exists()
    assert Snapshot.objects.filter(pk=snap.pk, complete=True).exists()
    assert Valuation.objects.filter(pk=published.pk).exists()
    assert Account.objects.filter(pk=account.pk).exists()
    assert Entity.objects.filter(pk=account.entity_id).exists()


def test_draft_delete_protects_published_and_missing_snapshots(logged, draft, snap):
    for page in ["/valuations/", f"/valuations/{snap.pk}/"]:
        assert f"/valuations/{snap.pk}/delete/" not in logged.get(page).content.decode()
    path = f"/valuations/{draft.pk}/delete/"
    assert logged.get(path).status_code == 200
    draft.complete = True
    draft.save()
    for pk in [snap.pk, draft.pk, max(snap.pk, draft.pk) + 1]:
        for method in [logged.get, logged.post]:
            assert method(f"/valuations/{pk}/delete/").status_code == 404
    assert Snapshot.objects.filter(pk=draft.pk, complete=True).exists()
    assert draft.valuations.count() == 1
    assert Position.objects.count() == 1
    assert draft.tax_adjustments.count() == 1


def test_draft_delete_requires_login_and_csrf(logged, draft):
    path = f"/valuations/{draft.pk}/delete/"
    anonymous = Client(enforce_csrf_checks=True)
    assert anonymous.get(path).status_code == 302
    assert anonymous.post(path).status_code in [302, 403]
    secure = Client(enforce_csrf_checks=True)
    secure.force_login(get_user_model().objects.get(username="tester"))
    assert secure.post(path).status_code == 403
    assert Snapshot.objects.filter(pk=draft.pk).exists()
    assert secure.get(path).status_code == 200
    token = secure.cookies["csrftoken"].value
    assert secure.post(path, {"csrfmiddlewaretoken": token}).status_code == 302
    assert not Snapshot.objects.filter(pk=draft.pk).exists()


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_draft_delete_rejects_other_methods(logged, draft, method):
    assert getattr(logged, method)(f"/valuations/{draft.pk}/delete/").status_code == 405
    assert Snapshot.objects.filter(pk=draft.pk).exists()



def snapshot_editor_body(client, snapshot, action):
    response = client.get(f"/valuations/{snapshot.pk}/")
    formset = response.context["formset"]
    body = {"editor_version": response.context["editor_version"], "form-TOTAL_FORMS": str(len(formset)),
            "form-INITIAL_FORMS": str(len(formset))}
    for i, form in enumerate(formset):
        for field, value in form.initial.items():
            body[f"form-{i}-{field}"] = "" if value is None else str(value)
    if action is not None:
        body["action"] = action
    return body


@pytest.mark.parametrize("imported", [False, True])
@pytest.mark.parametrize("lang", ["en", "nl"])
def test_published_editor_cannot_reopen_history(logged, draft, imported, lang):
    # Imported valuations use the same editor; include archived data in both paths.
    draft.imported = imported
    draft.save()
    path = f"/valuations/{draft.pk}/"
    body = snapshot_editor_body(logged, draft, "complete")
    body["form-0-amount"] = "124"
    assert logged.post(path, body).status_code == 302
    draft.refresh_from_db()
    assert draft.complete
    logged.cookies["django_language"] = lang
    html = logged.get(path).content.decode()
    assert 'value="draft"' not in html
    assert 'value="complete"' in html
    assert ("Opslaan" if lang == "nl" else "Save") in html
    # Replay an old draft form after publication, then try the delete endpoint.
    body["action"] = "draft"
    body["form-0-amount"] = "125"
    assert logged.post(path, body).status_code == 409
    draft.refresh_from_db()
    assert draft.complete and draft.imported == imported
    assert draft.valuations.get().amount_minor == 12400
    assert logged.post(f"{path}delete/").status_code == 404
    assert draft.valuations.get().positions.get().value_minor == 12345
    assert draft.tax_adjustments.get().amount_minor == -100


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("action", [None, "", "typo"])
def test_snapshot_editor_rejects_invalid_actions_without_mutation(logged, draft, complete, action):
    draft.complete = complete
    draft.save()
    body = snapshot_editor_body(logged, draft, action)
    body["form-0-amount"] = "999"
    assert logged.post(f"/valuations/{draft.pk}/", body).status_code == 400
    draft.refresh_from_db()
    assert draft.complete == complete
    assert draft.valuations.get().amount_minor == 12345
    assert draft.valuations.get().positions.get().value_minor == 12345
    assert draft.tax_adjustments.get().amount_minor == -100


def test_imported_published_history_survives_draft_save_and_delete(logged):
    import_overview(parse_overview(fixture_csv()))
    snapshot = Snapshot.objects.latest("date")
    observation = snapshot.valuations.filter(account__kind="broker").first()
    position = Position.objects.create(valuation=observation, name="Archived", value_minor=10000)
    adjustments = list(snapshot.tax_adjustments.values())
    body = snapshot_editor_body(logged, snapshot, "draft")
    assert logged.post(f"/valuations/{snapshot.pk}/", body).status_code == 302
    assert logged.post(f"/valuations/{snapshot.pk}/delete/").status_code == 404
    snapshot.refresh_from_db()
    assert snapshot.complete and snapshot.imported
    assert Position.objects.filter(pk=position.pk).exists()
    assert list(snapshot.tax_adjustments.values()) == adjustments


def test_draft_save_stays_draft_and_remains_deletable(logged, draft):
    body = snapshot_editor_body(logged, draft, "draft")
    assert logged.post(f"/valuations/{draft.pk}/", body).status_code == 302
    draft.refresh_from_db()
    assert not draft.complete
    assert logged.post(f"/valuations/{draft.pk}/delete/").status_code == 302


def test_published_draft_action_still_validates_company_tax_basis(logged, draft, account):
    account.kind = "broker"
    account.save()
    account.entity.kind = "company"
    account.entity.save()
    draft.complete = True
    draft.save()
    body = snapshot_editor_body(logged, draft, "draft")
    body["form-0-amount"] = "999"
    response = logged.post(f"/valuations/{draft.pk}/", body)
    assert response.status_code == 200
    assert "basis" in response.context["formset"][0].errors
    assert draft.valuations.get().amount_minor == 12345


def test_movement_details_expose_offsetting_transfers(owner, snap):
    from wealth.services import movement

    cash = Account.objects.create(name="Cash", entity=owner)
    broker = Account.objects.create(name="Broker", entity=owner, kind="broker")
    Valuation.objects.create(account=cash, snapshot=snap, amount_minor=20000)
    Valuation.objects.create(account=broker, snapshot=snap, amount_minor=10000, net_deposits_minor=10000)
    later = Snapshot.objects.create(date=date(2026, 5, 1), complete=True)
    Valuation.objects.create(account=cash, snapshot=later, amount_minor=15000)
    Valuation.objects.create(account=broker, snapshot=later, amount_minor=17000, net_deposits_minor=15000)
    bridge = movement(later)
    assert bridge["parts"][0]["details"][0]["amount"] == 2000
    residual = bridge["parts"][-1]
    assert residual["amount"] == 0
    assert {r["label"]: r["amount"] for r in residual["details"]} == {"Cash": -5000, "Broker": 5000}
    for part in bridge["parts"]:
        assert sum(r["amount"] for r in part["details"]) == part["amount"]


def test_movement_details_coverage_unknown_flows_joint_and_tax(owner, snap):
    from wealth.services import movement

    later = Snapshot.objects.create(date=date(2026, 5, 1), complete=True)
    closed = Account.objects.create(name="Closed", entity=owner, closed_on=later.date)
    added = Account.objects.create(name="New", entity=owner, started_on=later.date)
    broker = Account.objects.create(name="Unknown deposits", entity=owner, kind="broker")
    stale = Account.objects.create(name="Carried", entity=owner)
    joint = Account.objects.create(name="Joint", entity=owner, joint=True)
    older = Snapshot.objects.create(date=date(2025, 12, 1), complete=True)
    for account, snapshot, amount in [
        (closed, snap, 10000), (added, later, 25000),
        (broker, snap, 20000), (broker, later, 30000),
        (stale, older, 2000), (stale, later, 4000),
        (joint, snap, 10001), (joint, later, 10003),
    ]:
        Valuation.objects.create(account=account, snapshot=snapshot, amount_minor=amount)
    TaxAdjustment.objects.create(snapshot=snap, kind="bank_ab", amount_minor=-1000)
    TaxAdjustment.objects.create(snapshot=later, kind="bank_ab", amount_minor=-2000)
    bridge = movement(later)
    rows = {r["label"]: r for r in bridge["parts"][-1]["details"]}
    assert rows["Closed"]["amount"] == -10000 and rows["Closed"]["closing"] is None
    assert rows["New"]["amount"] == 25000 and rows["New"]["opening"] is None
    assert rows["Unknown deposits"]["amount"] == 10000
    assert rows["Carried"]["amount"] == 2000
    assert rows["Carried"]["opening_date"] == older.date
    assert rows["Joint"]["amount"] == 1
    assert bridge["parts"][3]["amount"] == -1000
    assert bridge["opening"] + sum(p["amount"] for p in bridge["parts"]) == bridge["closing"]
    for part in bridge["parts"]:
        assert sum(r["amount"] for r in part["details"]) == part["amount"]
        if part["key"] != "tax":
            assert [r["label"].lower() for r in part["details"]] == sorted(
                r["label"].lower() for r in part["details"]
            )


def test_movement_details_attribute_home_interest_and_keep_mortgage_residual(owner, snap):
    from wealth.services import movement

    later = Snapshot.objects.create(date=date(2026, 5, 1), complete=True)
    home = Account.objects.create(name="Home", entity=owner, kind="property")
    mortgage = Account.objects.create(name="Mortgage", entity=owner, kind="mortgage")
    claim = Account.objects.create(name="Deposit", entity=owner, kind="claim")
    for account, opening, closing, interest in [
        (home, 40000000, 41000000, None),
        (mortgage, -20000000, -19900000, None),
        (claim, 1000000, 902000, 2000),
    ]:
        Valuation.objects.create(account=account, snapshot=snap, amount_minor=opening)
        Valuation.objects.create(account=account, snapshot=later,
                                 amount_minor=closing, interest_minor=interest)
    bridge = movement(later)
    assert [p["amount"] for p in bridge["parts"]] == [0, 2000, 1000000, 0, 0]
    assert bridge["parts"][1]["details"][0]["account"] == claim
    assert bridge["parts"][2]["details"][0]["account"] == home
    assert {r["label"]: r["amount"] for r in bridge["parts"][-1]["details"]} == {
        "Mortgage": 100000, "Deposit": -100000,
    }
    assert bridge["opening"] + sum(p["amount"] for p in bridge["parts"]) == bridge["closing"]


@pytest.mark.parametrize("language", ["en", "nl"])
def test_movement_zero_unexplained_details_remain_inspectable(logged, owner, snap, language):
    from wealth.services import movement
    from django.conf import settings

    logged.cookies[settings.LANGUAGE_COOKIE_NAME] = language

    broker = Account.objects.create(name="Unknown deposits", entity=owner, kind="broker")
    carried = Account.objects.create(name="Carried broker", entity=owner, kind="broker")
    cash = Account.objects.create(name="Transfer source", entity=owner)
    other = Account.objects.create(name="Transfer destination", entity=owner)
    later = Snapshot.objects.create(date=date(2026, 5, 1), complete=True)
    Valuation.objects.create(account=carried, snapshot=snap, amount_minor=120045,
                             net_deposits_minor=100000)
    for snapshot, source, target in [(snap, 200000, 100000), (later, 150000, 150000)]:
        Valuation.objects.create(account=broker, snapshot=snapshot, amount_minor=123456)
        Valuation.objects.create(account=cash, snapshot=snapshot, amount_minor=source)
        Valuation.objects.create(account=other, snapshot=snapshot, amount_minor=target)
    with translation.override(language):
        bridge = movement(later)
        residual = bridge["parts"][-1]
        rows = {r["label"]: r for r in residual["details"]}
        assert bridge["opening"] == bridge["closing"]
        assert residual["amount"] == 0
        assert rows[broker.name]["amount"] == rows[carried.name]["amount"] == 0
        assert rows[carried.name]["closing_date"] == snap.date
        assert rows[broker.name]["reason"] != rows[carried.name]["reason"]
        assert not bridge["parts"][0]["details"]
        response = logged.get("/analysis/", {"at": later.pk})
        html = response.content.decode()
        for row in rows.values():
            assert row["reason"] in html
        for part in bridge["parts"]:
            assert f'id="movement-{part["key"]}"' in html
            assert sum(r["amount"] for r in part["details"]) == part["amount"]
        assert ("Explanation" if language == "en" else "Toelichting") in html


def test_maturities_aggregate_owned_gross_balances_without_interest(owner, snap):
    from wealth.services import maturity_calendar
    business = Entity.objects.create(name="Fictional company", kind="company")
    for name, entity, amount, joint in [
        ("Deposit one", owner, 1000000, False),
        ("Loan two", owner, 1500000, False),
        ("Shared test claim", owner, 10001, True),
        ("Company deposit", business, 400000, False),
    ]:
        claim = Account.objects.create(name=name, entity=entity, kind="claim", joint=joint,
            started_on=date(2025, 1, 1), matures_on=date(2026, 3, 31), rate_bps=500)
        Valuation.objects.create(snapshot=snap, account=claim, amount_minor=amount, interest_minor=90000)
    calendar = maturity_calendar(snap)
    assert calendar["quarters"] == [{"label": "Q1 2026", "private": 2505001,
                                     "business": 400000, "total": 2905001}]
    assert sum(r["amount"] for r in calendar["rows"] if r["account"].name in {"Deposit one", "Loan two"}) == 2500000
    assert calendar["chart"]["rows"][0]["observed"] == "2026-01-01"


def test_maturities_unknown_overdue_zero_and_missing_stay_separate(owner, snap):
    from wealth.services import maturity_calendar
    cases = [
        ("No end", None, 12300, "unknown"),
        ("Overdue loan", date(2025, 12, 31), 20000, "overdue"),
        ("Due today", snap.date, 30000, "scheduled"),
        ("Empty claim", date(2025, 12, 31), 0, "nonpositive"),
        ("Negative legacy claim", date(2026, 4, 1), -100, "nonpositive"),
        ("Missing balance", date(2026, 6, 1), None, "missing"),
        ("Both unknown", None, None, "missing"),
    ]
    for name, end, amount, status in cases:
        claim = Account.objects.create(name=name, entity=owner, kind="claim", matures_on=end)
        if amount is not None:
            Valuation.objects.create(snapshot=snap, account=claim, amount_minor=amount)
    calendar = maturity_calendar(snap)
    assert [(r["account"].name, r["status"]) for r in calendar["rows"]] == sorted([(c[0],c[3]) for c in cases], key=lambda item: item[0].lower())
    assert calendar["quarters"][0]["total"] == 30000
    assert next(r for r in calendar["rows"] if r["status"] == "unknown")["amount"] == 12300
    assert next(r for r in calendar["rows"] if r["account"].name == "Both unknown")["amount"] is None


def test_maturities_as_of_carries_published_values_and_excludes_replaced_claims(owner, snap):
    from wealth.services import maturity_calendar
    aggregate = Account.objects.create(name="Historical aggregate", entity=owner, kind="claim",
        closed_on=date(2026, 2, 1), matures_on=date(2025, 8, 1))
    replacement = Account.objects.create(name="Detailed deposit", entity=owner, kind="claim",
        started_on=date(2026, 2, 1), matures_on=date(2025, 8, 1))
    carried = Account.objects.create(name="Carried loan", entity=owner, kind="claim",
        matures_on=date(2026, 5, 1))
    Valuation.objects.create(snapshot=snap, account=aggregate, amount_minor=900000)
    Valuation.objects.create(snapshot=snap, account=carried, amount_minor=100000)
    draft = Snapshot.objects.create(date=date(2026, 1, 15))
    Valuation.objects.create(snapshot=draft, account=carried, amount_minor=999999)
    later = Snapshot.objects.create(date=date(2026, 2, 1), complete=True)
    Valuation.objects.create(snapshot=later, account=replacement, amount_minor=900000)
    future = Snapshot.objects.create(date=date(2026, 9, 1), complete=True)
    Valuation.objects.create(snapshot=future, account=carried, amount_minor=0)
    other = Account.objects.create(name="Non-claim", entity=owner, kind="bank", matures_on=date(2026, 5, 1))
    Valuation.objects.create(snapshot=later, account=other, amount_minor=10000)
    assert {r["account"].pk for r in maturity_calendar(snap)["rows"]} == {aggregate.pk, carried.pk}
    result = maturity_calendar(later)
    assert {r["account"].pk for r in result["rows"]} == {replacement.pk, carried.pk}
    row = next(r for r in result["rows"] if r["account"] == carried)
    assert row["stale"] and row["valuation"].snapshot == snap and row["amount"] == 100000
    assert sum(q["total"] for q in result["quarters"]) == 1000000


@pytest.mark.parametrize("language,title,amount,quarter", [
    ("en", "Maturity calendar", "1,234.56", "Q2 2026"),
    ("nl", "Vervalkalender", "1.234,56", "K2 2026"),
])
def test_maturity_view_localized_and_read_only(logged, owner, snap, language, title, amount, quarter):
    from wealth.preferences import cents_cookie_name
    claim = Account.objects.create(name="Fictional <claim>", entity=owner, kind="claim",
        matures_on=date(2026, 6, 1))
    Valuation.objects.create(snapshot=snap, account=claim, amount_minor=123456, interest_minor=321)
    draft = Snapshot.objects.create(date=date(2026, 7, 1))
    published = Snapshot.objects.create(date=date(2025, 8, 1), complete=True)
    TaxAdjustment.objects.create(snapshot=snap, kind="bank_ab", amount_minor=-123)
    before = (list(Valuation.objects.values()), list(TaxAdjustment.objects.values()), report(snap))
    logged.cookies["django_language"] = language
    logged.cookies[cents_cookie_name()] = "1"
    response = logged.get("/maturities/", {"at": snap.pk})
    assert response.status_code == 200
    assert response.context["selected"] == snap
    assert draft not in response.context["snapshots"]
    html = response.content.decode()
    assert title in html and amount in html and quarter in html
    assert 'tabindex="0"' in html and 'scope="col"' in html
    assert 'Fictional &lt;claim&gt;' in html and '\\u003Cclaim\\u003E' in html
    assert logged.get("/maturities/", {"at": draft.pk}).context["selected"] == published
    assert Client().get("/maturities/").status_code == 302
    assert list(Valuation.objects.values()) == before[0]
    assert list(TaxAdjustment.objects.values()) == before[1]
    assert report(snap) == before[2]


def test_maturity_calendar_empty_states(logged, owner):
    assert b"Publish a valuation" in logged.get("/maturities/").content
    Snapshot.objects.create(date=date(2026, 1, 1), complete=True)
    assert b"No active deposits or loans" in logged.get("/maturities/").content
