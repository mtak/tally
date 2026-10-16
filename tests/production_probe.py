"""Executed inside the disposable production image by production_smoke.py."""

import hashlib
import http.client
from http.cookies import SimpleCookie
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import time
from urllib.parse import urlencode


def database_digest(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()


mode = sys.argv[1]
if mode == "restore":
    backup = Path("/backups/verified.sqlite3")
    expected = Path("/backups/expected.sha256").read_text()
    assert database_digest(backup) == expected
    restored = Path("/data/tally.sqlite3")
    assert not restored.exists()
    shutil.copyfile(backup, restored)
    restored.chmod(0o600)
    os.chown(restored, 10001, 10001)
    assert database_digest(restored) == expected
    sys.exit(0)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from wealth.models import Account, Valuation

assert os.getuid() == os.getgid() == 10001
assert not settings.DEBUG
assert settings.TALLY_AUTH_ENABLED
assert settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE
assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
assert settings.ALLOWED_HOSTS == ["smoke.example.invalid"]
assert settings.CSRF_TRUSTED_ORIGINS == ["https://smoke.example.invalid"]
assert not Path("/data/.dev-login.json").exists()

if mode == "backup":
    destination = Path("/backups/verified.sqlite3")
    previous = os.umask(0o022)
    try:
        call_command("backup", str(destination))
    finally:
        os.umask(previous)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    expected = database_digest(destination)
    assert expected == database_digest(settings.DATABASES["default"]["NAME"])
    try:
        call_command("backup", str(destination))
    except CommandError:
        pass
    else:
        raise AssertionError("Backup overwrote an existing destination")
    assert database_digest(destination) == expected
    assert not list(destination.parent.glob(".tally-backup-*"))
    Path("/backups/expected.sha256").write_text(expected)
    sys.exit(0)

# Wait for the image's actual migration + Gunicorn entry point, without host ports.
cookies = SimpleCookie()


def request(method, path, body=None):
    headers = {"Host": "smoke.example.invalid", "X-Forwarded-Proto": "https"}
    if cookies:
        headers["Cookie"] = "; ".join(f"{key}={value.value}" for key, value in cookies.items())
    if body is not None:
        headers.update({
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://smoke.example.invalid",
            "Referer": "https://smoke.example.invalid/login/",
        })
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=3)
    try:
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        content = response.read().decode()
        for key, value in response.getheaders():
            if key.lower() == "set-cookie":
                cookies.load(value)
        return response.status, content, dict(response.getheaders())
    finally:
        connection.close()


for attempt in range(60):
    try:
        status, login, _ = request("GET", "/login/")
        assert status == 200
        break
    except (OSError, AssertionError, http.client.HTTPException):
        time.sleep(1)
else:
    raise AssertionError("Production image did not start within 60 seconds")

assert request("GET", "/")[0] == 302
if mode == "seed":
    call_command("seed_demo")
    get_user_model().objects.create_user("smoke-user", password="fictional-smoke-password")
assert Account.objects.filter(name="Everyday account").exists()
assert Valuation.objects.exists()
assert get_user_model().objects.get(username="smoke-user").check_password("fictional-smoke-password")
token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login).group(1)
assert cookies[settings.CSRF_COOKIE_NAME]["secure"]
status, _, _ = request("POST", "/login/", urlencode({
    "username": "smoke-user", "password": "fictional-smoke-password", "csrfmiddlewaretoken": token,
}))
assert status == 302
assert cookies[settings.SESSION_COOKIE_NAME]["secure"]
assert cookies[settings.SESSION_COOKIE_NAME]["httponly"]
status, dashboard, _ = request("GET", "/")
assert status == 200 and "smoke-user" in dashboard
assets = set(re.findall(r'(?:href|src)="(/static/[^"?]+)', dashboard))
assert any(path.endswith(".css") for path in assets)
assert any(path.endswith(".js") for path in assets)
for path in assets:
    status, content, headers = request("GET", path)
    assert status == 200 and content, path
    assert "Cache-Control" in headers, path
print(f"Production {mode}: migrations, secure login, dashboard and {len(assets)} static assets passed.")
