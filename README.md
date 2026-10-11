# Tally

Self-hosted, bilingual personal wealth tracker. Django 5.2 LTS, SQLite, HTMX and
Apache ECharts. English (default) and Dutch. Dark mode by default, with optional light mode. All assets served locally.

## Local development (Docker, no Traefik)

    docker compose -p tally-dev -f compose.yaml -f compose.dev.yaml up --build -d
    docker compose -p tally-dev -f compose.yaml -f compose.dev.yaml exec app python manage.py createsuperuser

Open http://localhost:8000. To populate an empty portfolio with fictional data:

    docker compose -p tally-dev -f compose.yaml -f compose.dev.yaml exec app python manage.py seed_demo

Use a separate Compose project for real data. Never import real history into the demo
database. Development binds to localhost only.

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

## Workflow

Add owners and accounts, then start a valuation on any date. Enter full EUR balances:
joint bank accounts count at 50%, other assets at 100%. Mortgages are negative.
Save a draft or publish it. Blank is not zero: older available observations retain
their original date and are flagged. Closed accounts disappear on/after their closing
date, while earlier history remains.

For broker accounts, choose period totals between explicit valuation dates, or
cumulative deposit/withdrawal counters. Cumulative tracking starts with a baseline
valuation and starting counters; later matching counters yield the period flows.
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
