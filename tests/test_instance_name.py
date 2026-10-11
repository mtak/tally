"""Instance labels are shared by public and authenticated application pages."""

import pytest
from django.test import Client
from django.utils.html import escape

from django.contrib.auth import get_user_model


@pytest.fixture
def logged():
    client = Client()
    user = get_user_model().objects.create_user(username="instance-tester", password="fictional-test-only")
    client.force_login(user)
    return client

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("language", ["en", "nl"])
@pytest.mark.parametrize("name", ["Example portfolio", "Example & Co <script>alert(1)</script>"])
def test_instance_name_on_login_and_authenticated_pages(settings, logged, language, name):
    settings.TALLY_INSTANCE_NAME = name
    for client, path in [(Client(), "/login/"), (logged, "/"), (logged, "/accounts/")]:
        client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
        response = client.get(path)
        assert response.status_code == 200
        html = response.content.decode()
        assert f"<title>Tally · {escape(name)}</title>" in html
        assert f'class="workspace-label instance-name">{escape(name)}</span>' in html
        assert "<script>alert(1)</script>" not in html


@pytest.mark.parametrize("name", ["", "   "])
@pytest.mark.parametrize("language,label", [("en", "Personal wealth"), ("nl", "Persoonlijk vermogen")])
def test_blank_name_preserves_default_ui(settings, language, label, name):
    settings.TALLY_INSTANCE_NAME = name
    client = Client()
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
    response = client.get("/login/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "<title>Tally</title>" in html
    assert f'class="workspace-label">{label}</span>' in html


def test_instance_name_trims_surrounding_whitespace(settings):
    settings.TALLY_INSTANCE_NAME = "  Example portfolio  "
    response = Client().get("/login/")
    assert "<title>Tally · Example User A&#x27;s portfolio</title>" in response.content.decode()
