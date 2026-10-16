import os
import re
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
TALLY_INSTANCE_NAME = os.getenv("TALLY_INSTANCE_NAME", "").strip()
TALLY_TRAEFIK_ID = os.getenv("TALLY_TRAEFIK_ID", "tally")
if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", TALLY_TRAEFIK_ID):
    raise ImproperlyConfigured(
        "TALLY_TRAEFIK_ID must be 1–63 lowercase letters, digits, underscores or "
        "hyphens, starting with a letter or digit."
    )
TALLY_GIT_COMMIT = os.getenv("TALLY_GIT_COMMIT", "").strip()
_auth_enabled = os.getenv("TALLY_AUTH_ENABLED", "1")
if _auth_enabled not in {"0", "1"}:
    raise ImproperlyConfigured("TALLY_AUTH_ENABLED must be 1 (enabled) or 0 (disabled).")
TALLY_AUTH_ENABLED = _auth_enabled == "1"
_import_history_enabled = os.getenv("TALLY_IMPORT_HISTORY_ENABLED", "1")
if _import_history_enabled not in {"0", "1"}:
    raise ImproperlyConfigured(
        "TALLY_IMPORT_HISTORY_ENABLED must be 1 (enabled) or 0 (disabled)."
    )
TALLY_IMPORT_HISTORY_ENABLED = _import_history_enabled == "1"
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY", "development-only-change-me" if DEBUG else ""
)
if not SECRET_KEY:
    # Management commands/tests can use a nonpersistent key; production requires one.
    import sys

    if (
        any(
            x in sys.argv
            for x in ["collectstatic", "test", "makemigrations", "compilemessages"]
        )
        or "pytest" in sys.modules
    ):
        SECRET_KEY = "build-and-test-only"
    else:
        raise RuntimeError(
            "Set DJANGO_SECRET_KEY (or DJANGO_DEBUG=1 for local development)."
        )
ALLOWED_HOSTS = os.getenv(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver"
).split(",")
CSRF_TRUSTED_ORIGINS = [
    x for x in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if x
]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "wealth",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "config.middleware.PreferenceLocaleMiddleware",
    "wealth.preferences.MoneyPreferenceMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "config.context_processors.instance_name",
                "config.context_processors.authentication",
                "config.context_processors.import_history",
                "config.context_processors.release",
                "config.context_processors.maturity_navigation",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
DATA_DIR = Path(os.getenv("TALLY_DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "tally.sqlite3",
        "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
    }
}
LANGUAGE_CODE = "en"
LANGUAGES = [("nl", "Nederlands"), ("en", "English")]
USE_I18N = True
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = os.getenv("TZ", "Europe/Amsterdam")
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
SESSION_COOKIE_NAME = os.getenv("TALLY_SESSION_COOKIE_NAME", "sessionid")
CSRF_COOKIE_NAME = os.getenv("TALLY_CSRF_COOKIE_NAME", "csrftoken")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if os.getenv("TALLY_TRUST_PROXY", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
