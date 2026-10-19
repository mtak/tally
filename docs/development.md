# Development

Tally uses Django 5.2 LTS, SQLite, HTMX, and Apache ECharts. English is the default
language, with Dutch available. Dark mode is the first-visit default; light mode is
also available. HTMX 2.0.11 and ECharts 6.0.0 are vendored with their licenses in
`static/vendor`. Runtime assets are served locally; there are no remote scripts,
fonts, analytics, or quote requests.

## Docker Compose with Make

Install Docker with Compose v2 and GNU Make. From the repository root:

```sh
make up
```

For a portfolio pre-filled with fictional data:

```sh
make demo TALLY_INSTANCE_NAME=tally-demo
```

Both commands build the image, apply migrations, start the app, and show its URL and
login. The default instance is `tally-dev` at <http://localhost:8000>. A local
administrator is created with a random password saved with mode 600 in
`/data/.dev-login.json` in that instance's persistent volume. Restarts reuse this
login. This convenience command requires DEBUG and is for local development only.
Existing passwords are never reset. If the saved credentials no longer match, or an
existing `tally-dev` user has no saved password, the command reports an error.

Use the same `TALLY_INSTANCE_NAME` on every command for that instance. It selects
the Compose project and its separate database and backup volumes, and Make passes it
to the application header, overriding a value from an environment file. Names must
start with a lowercase letter or digit and contain only lowercase letters, digits,
hyphens, or underscores.

For simultaneous instances, give each its own project, port, and session/CSRF cookie
names:

```sh
make demo TALLY_INSTANCE_NAME=tally-demo-2 TALLY_DEV_PORT=8002 \
  TALLY_SESSION_COOKIE_NAME=tally_demo_2_session \
  TALLY_CSRF_COOKIE_NAME=tally_demo_2_csrf
```

Environment files are optional. Use a separate ignored file for each local instance.
`TALLY_DEV_PORT` defaults to 8000; command-line options override environment-file
values. The same precedence applies to `TALLY_SESSION_COOKIE_NAME` and
`TALLY_CSRF_COOKIE_NAME`. Select an environment file with `TALLY_ENV_FILE`, for
example `make up TALLY_ENV_FILE=.env.personal`; pass it on each Make command that
targets the instance.

Available commands (add the same instance/environment options used at startup):

| Command | Purpose |
| --- | --- |
| `make help` | List commands and options. |
| `make seed` | Add fictional data to a running, empty portfolio. |
| `make login` | Show the URL and saved development credentials again. |
| `make superuser` | Interactively create another administrator. |
| `make logs` | Follow application logs. |
| `make down` | Stop the instance while preserving its database, backups, and login. |

`make demo` starts the app and then seeds it. Seeding refuses a portfolio that
already has accounts or valuations; it never clears existing data. Use `make up` to
restart an existing instance. Each portfolio needs its own Compose project and
volume. Keep personal data separate from fictional demo data. Development binds to
localhost only.

Equivalent startup without Make:

```sh
docker compose -p tally-dev -f compose.yaml -f compose.dev.yaml up --build -d
docker compose -p tally-dev -f compose.yaml -f compose.dev.yaml exec app python manage.py createsuperuser
docker compose -p tally-dev -f compose.yaml -f compose.dev.yaml exec app python manage.py seed_demo
```

## Release identification

The app's version label includes the image's seven-character Git commit; hover to
see the full SHA. On mobile it appears in the page footer. `make up` and `make demo`
pass the checkout's commit automatically. When building directly with Compose, set
the commit immediately before the build:

```sh
export TALLY_GIT_COMMIT="$(git rev-parse HEAD)"
```

For plain Docker:

```sh
docker build --build-arg TALLY_GIT_COMMIT="$(git rev-parse HEAD)" -t tally .
```

Build releases from a clean checkout. Commit metadata is baked into the image, so
rebuild to update it. Without metadata, only the version appears. For development
without Docker, optionally export `TALLY_GIT_COMMIT` before starting Django.

## Instance display and amount precision

Set `TALLY_INSTANCE_NAME="Example portfolio"` in the instance environment file to
show a distinct name in the shared header (including before login) and browser
title. Use a different name for each person's instance. Blank or omitted names keep
the default appearance. Docker Compose passes the setting in development and
production; recreate the app with the usual Compose command and `up -d` after
changing it. For development, select the file with `TALLY_ENV_FILE`; without Docker,
export the variable before starting Django.

Set `TALLY_MONEY_PRECISION=whole` (default) or `TALLY_MONEY_PRECISION=cents` in the
instance environment to control monetary display and input precision for every
browser using that instance. Restart the app after changing it. Stored values and
calculations always retain exact cents.

## Run Django without Docker

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
DJANGO_DEBUG=1 .venv/bin/python manage.py migrate
DJANGO_DEBUG=1 .venv/bin/python manage.py createsuperuser
DJANGO_DEBUG=1 .venv/bin/python manage.py runserver
```

Run the existing verification commands when appropriate:

```sh
.venv/bin/pytest
.venv/bin/python manage.py makemigrations --check --dry-run
```

Translations use Django gettext:

```sh
DJANGO_DEBUG=1 .venv/bin/python manage.py makemessages -l nl --ignore=.venv
DJANGO_DEBUG=1 .venv/bin/python manage.py compilemessages --ignore=.venv
```

Keep real exports, `.env` files, databases, backups, and CSVs out of Git and Docker.
They are ignored by the repository. Fixtures and screenshots must contain fictional
amounts only. When developing with real history, keep it in a separate Compose
project and volume with its own ignored environment file, port, and cookie names;
development instances are not production deployments.
