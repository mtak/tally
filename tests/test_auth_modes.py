"""Portfolio authentication can be delegated without changing Django identities."""
import os
import subprocess
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from wealth.models import Account, Entity, ImportRecord, Snapshot, Valuation
from test_tally import fixture_csv, snapshot_editor_body

pytestmark = pytest.mark.django_db


@pytest.fixture
def portfolio():
    owner = Entity.objects.create(name="Fictional owner", kind="private")
    account = Account.objects.create(name="Fictional bank", entity=owner)
    snapshot = Snapshot.objects.create(date=date(2026, 9, 1))
    return owner, account, snapshot


def portfolio_pages(account, snapshot):
    return ["/", "/analysis/", "/maturities/", "/accounts/", "/accounts/new/",
            f"/accounts/{account.pk}/", "/owners/new/", "/valuations/",
            "/valuations/new/", f"/valuations/{snapshot.pk}/",
            f"/valuations/{snapshot.pk}/delete/", "/import/", "/export/"]


@pytest.mark.parametrize("enabled", [True, False])
def test_portfolio_access_in_both_modes(settings, portfolio, enabled):
    settings.TALLY_AUTH_ENABLED = enabled
    _, account, snapshot = portfolio
    client = Client()
    for path in portfolio_pages(account, snapshot):
        response = client.get(path)
        if enabled:
            assert response.status_code == 302, path
            assert response.url.startswith("/login/?next="), path
        else:
            assert response.status_code == 200, path
    assert get_user_model().objects.count() == 0


def test_default_mode_rejects_anonymous_writes_and_identity_headers(settings, portfolio):
    assert settings.TALLY_AUTH_ENABLED is True
    _, account, snapshot = portfolio
    client = Client(HTTP_REMOTE_USER="admin", HTTP_X_FORWARDED_USER="admin",
                    HTTP_CF_ACCESS_AUTHENTICATED_USER_EMAIL="fictional@example.invalid")
    for path in ["/owners/new/", "/accounts/new/",
                 f"/accounts/{account.pk}/", "/valuations/new/",
                 f"/valuations/{snapshot.pk}/", f"/valuations/{snapshot.pk}/delete/",
                 "/import/"]:
        response = client.post(path, {})
        assert response.status_code == 302
        assert response.url.startswith("/login/?next=")
    assert Entity.objects.count() == Account.objects.count() == Snapshot.objects.count() == 1
    assert not Valuation.objects.exists()
    assert not get_user_model().objects.exists()


def test_import_history_can_be_disabled(settings, portfolio):
    assert settings.TALLY_IMPORT_HISTORY_ENABLED is True
    settings.TALLY_AUTH_ENABLED = False
    settings.TALLY_IMPORT_HISTORY_ENABLED = False
    client = Client()

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert b"Import history" not in dashboard.content
    assert client.get("/import/").status_code == 404
    assert client.post("/import/", {}).status_code == 404

    user = get_user_model().objects.create_user(username="fictional", password="test-only")
    client.force_login(user)
    assert client.get("/import/").status_code == 404
    assert client.post("/import/", {}).status_code == 404


@pytest.mark.parametrize("enabled", [True, False])
def test_writes_and_csrf_in_both_modes(settings, portfolio, enabled):
    settings.TALLY_AUTH_ENABLED = enabled
    owner, account, snapshot = portfolio
    client = Client(enforce_csrf_checks=True)
    if enabled:
        user = get_user_model().objects.create_user(username="fictional", password="test-only")
        client.force_login(user)
    client.get("/accounts/")
    token = client.cookies["csrftoken"].value
    for path in ["/owners/new/", "/accounts/new/",
                 f"/accounts/{account.pk}/", "/valuations/new/",
                 f"/valuations/{snapshot.pk}/", f"/valuations/{snapshot.pk}/delete/",
                 "/import/", "/logout/"]:
        assert client.post(path, {}).status_code == 403, path
    assert not Valuation.objects.exists()
    assert Snapshot.objects.count() == 1
    assert Account.objects.count() == 1
    assert not ImportRecord.objects.exists()

    def post(path, data):
        return client.post(path, data, HTTP_X_CSRFTOKEN=token)

    assert post("/owners/new/", {"name": "Second fictional owner", "kind": "private"}).status_code == 302
    assert Entity.objects.count() == 2
    account_data = {"name": "New fictional bank", "entity": owner.pk,
                    "kind": "bank", "asset_class": "cash", "currency": "EUR"}
    assert post("/accounts/new/", account_data).status_code == 302
    account_data["name"] = "Edited fictional bank"
    assert post(f"/accounts/{account.pk}/", account_data).status_code == 302
    account.refresh_from_db()
    assert account.name == "Edited fictional bank"
    assert post("/valuations/new/", {"date": "2026-10-01", "ab_rate": "26.9", "vpb_rate": "19"}).status_code == 302
    new = Snapshot.objects.get(date=date(2026, 10, 1))
    body = snapshot_editor_body(client, snapshot, "complete")
    for i in range(int(body["form-TOTAL_FORMS"])):
        body[f"form-{i}-amount"] = "125"
    assert post(f"/valuations/{snapshot.pk}/", body).status_code == 302
    snapshot.refresh_from_db()
    assert snapshot.complete
    assert snapshot.valuations.count() == 2
    # The stale token still cannot overwrite the published observation.
    assert post(f"/valuations/{snapshot.pk}/", body).status_code == 409
    assert post(f"/valuations/{snapshot.pk}/delete/", {}).status_code == 404
    assert post(f"/valuations/{new.pk}/delete/", {}).status_code == 302
    assert not Snapshot.objects.filter(pk=new.pk).exists()
    assert post("/import/", {"file": SimpleUploadedFile("fictional.csv", fixture_csv()),
                             "confirm": "on"}).status_code == 302
    assert ImportRecord.objects.count() == 1
    export = client.get("/export/")
    assert export.status_code == 200
    assert "Edited fictional bank" in export.content.decode()


@pytest.mark.parametrize("enabled", [True, False])
def test_login_logout_and_navigation(settings, enabled):
    settings.TALLY_AUTH_ENABLED = enabled
    client = Client(enforce_csrf_checks=True)
    response = client.get("/login/?next=https://untrusted.example")
    assert response.status_code == (200 if enabled else 302)
    if not enabled:
        assert response.url == "/"
        assert client.post("/login/", {"username": "ignored"}).status_code == 403
        html = client.get("/").content.decode()
        assert 'id="show-cents"' not in html
        assert 'action="/logout/"' not in html
        assert 'class="user-name"' not in html
    token = client.cookies["csrftoken"].value
    user = get_user_model().objects.create_user(username="fictional", password="test-only", is_staff=True)
    client.force_login(user)
    html = client.get("/").content.decode()
    assert 'id="show-cents"' not in html
    assert ('action="/logout/"' in html) == enabled
    assert ('class="user-name"' in html) == enabled
    assert client.get("/logout/").status_code == 405
    assert client.post("/logout/").status_code == 403
    response = client.post("/logout/", HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 302
    assert response.url == ("/login/" if enabled else "/")
    assert ("_auth_user_id" in client.session) == (not enabled)


@pytest.mark.parametrize("enabled", [True, False])
def test_admin_keeps_separate_staff_boundary(settings, enabled):
    settings.TALLY_AUTH_ENABLED = enabled
    client = Client()
    assert client.get("/admin/").url.startswith("/admin/login/")
    assert client.get("/admin/login/").status_code == 200
    user = get_user_model().objects.create_user(username="ordinary", password="test-only")
    client.force_login(user)
    assert client.get("/admin/").url.startswith("/admin/login/")
    user.is_staff = True
    user.save()
    assert client.get("/admin/").status_code == 200
    # Staff status alone does not grant model permissions or superuser status.
    assert client.get("/admin/wealth/account/").status_code == 403
    user.refresh_from_db()
    assert not user.is_superuser


@pytest.mark.parametrize("value, expected", [(None, "True"), ("1", "True"), ("0", "False"),
                                            ("false", None), ("", None), ("typo", None)])
def test_environment_switch_is_explicit(value, expected, tmp_path):
    env = {**os.environ, "DJANGO_DEBUG": "1", "TALLY_DATA_DIR": str(tmp_path)}
    env.pop("TALLY_AUTH_ENABLED", None)
    if value is not None:
        env["TALLY_AUTH_ENABLED"] = value
    result = subprocess.run([os.sys.executable, "-c",
                             "from config.settings import TALLY_AUTH_ENABLED; print(TALLY_AUTH_ENABLED)"],
                            env=env, capture_output=True, text=True)
    if expected is None:
        assert result.returncode != 0
        assert "TALLY_AUTH_ENABLED must be" in result.stderr
    else:
        assert result.returncode == 0
        assert result.stdout.strip() == expected
