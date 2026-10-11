# Tally

Self-hosted, bilingual personal wealth tracker. Django 5.2 LTS, SQLite, HTMX and
Apache ECharts. English (default) and Dutch. Dark mode by default, with optional light mode. All assets served locally.

## Local development (Docker, no Traefik)

Install Docker with Compose v2 and GNU Make. Start a local instance:

    make up

For an instance with fictional test data:

    make demo TALLY_INSTANCE_NAME=tally-demo

Both commands build the image, apply migrations and start the app. The output shows
the URL, username and password, so you can log in immediately. The default instance
name is `tally-dev` and the default URL is http://localhost:8000. A `tally-dev`
administrator is created with a random password; its credentials are saved with mode
600 in `/data/.dev-login.json` in that instance's persistent volume. Restarts reuse
the login. This convenience command requires DEBUG and is only for local development.
Existing user passwords are never reset; if the saved login was changed or an existing
`tally-dev` user has no saved password, the command reports an error.

Set the instance name on **every** command targeting that instance. The name selects
the Compose project, giving each instance separate database and backup volumes.
Use a Compose-compatible name: lowercase letters, digits, hyphens or underscores,
starting with a letter or digit. Make also passes this name to the application header,
overriding `TALLY_INSTANCE_NAME` from an environment file.
When running instances simultaneously, choose distinct ports and cookie names:

    make demo TALLY_INSTANCE_NAME=tally-demo-2 TALLY_DEV_PORT=8002 TALLY_SESSION_COOKIE_NAME=tally_demo_2_session TALLY_CSRF_COOKIE_NAME=tally_demo_2_csrf

Environment files are optional. For the existing real-data development instance:

    make up TALLY_INSTANCE_NAME=tally-local TALLY_ENV_FILE=.env.local

`TALLY_DEV_PORT` can be supplied on the command line or in the environment file
(default 8000). Command-line options override values from the environment file.
The same applies to `TALLY_SESSION_COOKIE_NAME` and `TALLY_CSRF_COOKIE_NAME`.

Other commands (add the same instance/environment options as used for startup):

    make help           # List commands and options
    make seed           # Add fictional data to a running, empty portfolio
    make login          # Display the URL and saved development credentials again
    make superuser      # Interactively create an additional administrator
    make logs           # Follow application logs
    make down           # Stop the instance; keep its database, backups and login

`make demo` runs startup followed by `make seed`. Seeding refuses a portfolio that
already has accounts or valuations; it never clears existing data. Use `make up` to
restart an existing instance. Use a separate Compose project for real data and never
seed or import real history into a demo database. Development binds to localhost only.

Without Make, the equivalent startup and seeding commands are:

    docker compose -p tally-dev -f compose.yaml -f compose.dev.yaml up --build -d
    docker compose -p tally-dev -f compose.yaml -f compose.dev.yaml exec app python manage.py createsuperuser
    docker compose -p tally-dev -f compose.yaml -f compose.dev.yaml exec app python manage.py seed_demo

See [AGENT.md](AGENT.md) for the project handoff and [DEPLOYMENT.md](DEPLOYMENT.md) for the full production runbook.

## Production behind Traefik

Copy .env.example to .env and set a random DJANGO_SECRET_KEY, hostname and existing
Traefik network. Configure a certificate using your Traefik setup (add a certresolver
label if required).

    docker compose -p tally-prod -f compose.yaml -f compose.prod.yaml up --build -d
    docker compose -p tally-prod -f compose.yaml -f compose.prod.yaml exec app python manage.py createsuperuser

No public production port is mapped. Only enable TALLY_TRUST_PROXY behind a trusted
proxy. Configure TLS and VPN/private access or login rate limiting in your existing
Traefik setup. Container runs unprivileged; SQLite lives on a local volume, not NFS/R2.

One instance represents one portfolio: every authenticated user in that instance can
access the portfolio. Separate logins are NOT data isolation. Use separate Compose
projects and volumes for separate portfolios.

## Instance names

Set `TALLY_INSTANCE_NAME="Example portfolio"` in the instance's environment file to
show a distinctive name in the shared header (including login) and browser title.
Use a different name for each person's instance. Blank or omitted names keep the
default appearance. Docker Compose passes the setting in development and production;
recreate the app with your usual Compose command and `up -d` after changing it.
For development, select the environment file with `--env-file`. Without Docker,
export the variable before starting Django. The name is visible before login.

## Workflow

Add owners and accounts, then start a valuation on any date. Enter full EUR balances:
joint bank accounts count at 50%, other assets at 100%. Mortgages are negative.
Save a draft or publish it. Blank is not zero: older available observations retain
their original date and are flagged. Closed accounts disappear on/after their closing
date, while earlier history remains.

For broker accounts, choose period totals between explicit valuation dates, or
cumulative deposit/withdrawal counters. Cumulative tracking starts with a baseline
valuation and starting counters; later matching counters yield the period flows.
Cumulative totals cover complete history since account opening from a zero balance,
as confirmed by the user. Total euro result (value minus deposits plus withdrawals)
is shown on the first reading, independently of the period comparison.
Counter decreases require correction or an explicit new baseline. Switching modes
preserves inactive inputs. Backdated valuations do not change recorded flow periods.
Use “No deposits or withdrawals” to confirm zero flows; blank means unknown.
Tax basis is a separate input used for the liquidation scenario. Add current positions,
including cash, for asset allocation. EUR position value is authoritative. Optional
ISIN/ticker, exchange, currency, quantity and price prepare for future quote adapters.
No automatic quote connection is made.

Only underlying company accounts are valued: do not add participation value again
on top of subsidiaries' assets. Sole-proprietor assets are not classified as Box 2.

## Historical import

Use Import history to preview the agreed Overview CSV, then select the file again
and check confirmation. It preserves historical tax adjustments/source totals and
recalculates chart breakdowns. Duplicate dates/files are rejected atomically.
The confirmed malformed header '€ 12.345' maps to 2025-08-01. Consultancy is closed
from 2024-01-01, its first absent source date; adjust if you know the precise date.
The new joint account has no invented historical balance.

CSV values are rounded displayed euros: small differences with source totals can
remain. Individual positions and historic flows are not invented. Files are not retained.

    python manage.py import_overview /path/to/Overview.csv
    python manage.py import_overview /path/to/Overview.csv --apply

## Calculation conventions

Money: integer EUR cents; calculations: Python Decimal, half-up rounding. Exact
optional quantities/prices are stored as decimal strings, avoiding SQLite REAL.

- Result = closing - opening - deposits + withdrawals.
- Estimated period return = result / (opening + 0.5 × net contributions).
  Midpoint flow assumption; not annualized, not exact time-weighted performance.
  Unavailable for nonpositive estimated invested capital.
- Bank AB = -company bank balances × AB rate.
- Broker VPB = -(value - tax basis) × VPB rate.
- Broker AB = -(value + VPB adjustment) × AB rate.
- Example rates are 26.9% AB, 19% VPB. A loss produces a
  positive VPB correction. These are assumptions, not statutory tax advice.
- Imported historical tax corrections take precedence and remain unchanged when
  editing the associated balances.
- Net wealth deducts mortgages and scenario tax. Allocation shows gross assets.
  Liquidity includes mortgages but displays tax separately. Unallocated positions
  appear as Other.
- Account flows explain account return, not household income/spending.
  Internal transfers do not constitute total-wealth growth.

## Backup and restore

Use the SQLite online backup API, not a file copy of an active database:

    docker compose -p tally-prod -f compose.yaml -f compose.prod.yaml exec app python manage.py backup /backups/tally-2026-10-11.sqlite3

Copy the backup out using docker compose cp and your existing encrypted off-host
backup process. No external backup service is configured.

Restore while the app is stopped: preserve the existing volume, replace
/data/tally.sqlite3 with the verified backup, remove stale -wal/-shm companions for
that stopped database, preserve ownership 10001:10001, restart and verify.
Test restoring into a separate Compose project first. Backups include login and
financial data. CSV export is portable observation data, not a full backup.

## Development without Docker

    python3 -m venv .venv
    .venv/bin/pip install -r requirements-dev.txt
    DJANGO_DEBUG=1 .venv/bin/python manage.py migrate
    DJANGO_DEBUG=1 .venv/bin/python manage.py createsuperuser
    DJANGO_DEBUG=1 .venv/bin/python manage.py runserver
    .venv/bin/pytest
    .venv/bin/python manage.py makemigrations --check --dry-run

Translations use Django gettext:

    DJANGO_DEBUG=1 .venv/bin/python manage.py makemessages -l nl --ignore=.venv
    DJANGO_DEBUG=1 .venv/bin/python manage.py compilemessages --ignore=.venv

HTMX 2.0.11 and ECharts 6.0.0 are vendored with licenses in static/vendor.
There are no remote scripts, fonts, analytics or quote requests at runtime.

Real exports, .env, databases, backups and CSVs are ignored by Git and Docker.
Test and demonstration fixtures must use fictional amounts only.

## Change analysis

The waterfall reconciles consecutive published valuations using matching-period account
results, explicitly entered bank/claim interest, property revaluation and tax correction
changes. Remaining income/spending, missing flows, mortgage principal movements and
changes in coverage stay in Other / unexplained. Interest should be entered once, on
the earning account, even when paid into another tracked account.

## Local development with real history

Keep demonstration and real portfolios in separate Compose projects/volumes.
The development port and session/CSRF cookie names can be set through an ignored
environment file, allowing both instances to run on localhost without login conflicts.

The locally prepared real-data instance uses .env.local (mode 600), project tally-local
and port 8001:

    docker compose --env-file .env.local -p tally-local -f compose.yaml -f compose.dev.yaml up --build -d

Open http://localhost:8001. Its login is separate from the demo. The configuration file
contains a unique secret and must not be committed. To reproduce this setup elsewhere,
create an ignored .env.local with TALLY_DEV_PORT=8001, TALLY_SESSION_COOKIE_NAME=tally_local_session,
TALLY_CSRF_COOKIE_NAME=tally_local_csrf and a newly generated DJANGO_SECRET_KEY.
Create your login and import your own CSV; do not seed demo data in this instance.

This is a local development environment with DEBUG enabled and a loopback-only port,
not the server's production deployment.
