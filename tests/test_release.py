"""The shared release label identifies the built image, including before login."""

import pytest
from django.test import Client


@pytest.mark.django_db
@pytest.mark.parametrize("language", ["en", "nl"])
@pytest.mark.parametrize("commit", ["", "   ", "  a1b2c3d4e5f6789012345678901234567890abcd  "])
def test_release_label(settings, language, commit):
    settings.TALLY_GIT_COMMIT = commit
    client = Client()
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
    for path in ["/login/", "/", "/accounts/"]:
        settings.TALLY_AUTH_ENABLED = path == "/login/"
        response = client.get(path)
        assert response.status_code == 200
        html = response.content.decode()
        assert 'class="mobile-release"' in html
        if commit.strip():
            label = f'Tally · v0.1 · <span title="{commit.strip()}">a1b2c3d</span>'
            assert html.count(label) == 2
        else:
            assert html.count("Tally · v0.1\n") == 2
            assert 'title="   "' not in html
