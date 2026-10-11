import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db


@pytest.fixture
def login_dir(settings, tmp_path):
    settings.DEBUG = True
    settings.DATA_DIR = tmp_path
    return tmp_path


def test_development_login_is_private_valid_and_reused(login_dir, client):
    first = io.StringIO()
    call_command("dev_login", stdout=first)
    path = login_dir / ".dev-login.json"
    credentials = json.loads(path.read_text())
    assert path.stat().st_mode & 0o777 == 0o600
    assert client.login(**credentials)
    user = get_user_model().objects.get(username=credentials["username"])
    assert user.is_superuser and user.is_staff
    second = io.StringIO()
    call_command("dev_login", stdout=second)
    assert first.getvalue() == second.getvalue()
    assert get_user_model().objects.count() == 1
    assert credentials["password"] in first.getvalue()


def test_development_login_is_disabled_in_production(login_dir, settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEBUG"):
        call_command("dev_login")
    assert not (login_dir / ".dev-login.json").exists()
    assert not get_user_model().objects.exists()


def test_existing_user_password_is_not_reset(login_dir):
    user = get_user_model().objects.create_user("tally-dev", password="existing-test-password")
    with pytest.raises(CommandError, match="already exists"):
        call_command("dev_login")
    user.refresh_from_db()
    assert user.check_password("existing-test-password")
    assert not (login_dir / ".dev-login.json").exists()


def test_changed_password_is_not_reset(login_dir):
    call_command("dev_login", stdout=io.StringIO())
    user = get_user_model().objects.get(username="tally-dev")
    user.set_password("changed-test-password")
    user.save()
    with pytest.raises(CommandError, match="no longer works"):
        call_command("dev_login")
    user.refresh_from_db()
    assert user.check_password("changed-test-password")


@pytest.mark.parametrize("contents", ["not JSON", "{}", "[]"])
def test_invalid_saved_credentials_report_an_error(login_dir, contents):
    (login_dir / ".dev-login.json").write_text(contents)
    with pytest.raises(CommandError, match="Cannot read"):
        call_command("dev_login")
    assert not get_user_model().objects.exists()


def test_credentials_write_failure_rolls_back_user(login_dir, monkeypatch):
    def fail_write(*args):
        raise OSError("Simulated full disk")

    monkeypatch.setattr("wealth.management.commands.dev_login.json.dump", fail_write)
    with pytest.raises(CommandError, match="Cannot save"):
        call_command("dev_login")
    assert not get_user_model().objects.exists()
    assert not (login_dir / ".dev-login.json").exists()
