# Tally: conversation handoff and working instructions

## Start here

- Product: Tally, a personal wealth tracker for the personal wealth tracker project.
- Project repository: https://github.com/OWNER/REPOSITORY
- Existing local checkout: /path/to/tally
- ChatGPT project mirror:
  /home/user/.codex/.chatgpt-projects/[local project id]
- Reuse this checkout and inspect git status before editing. Preserve user changes.
- Read README.md, docs/decisions.md, and relevant code before changing behavior.
- Production instructions are in DEPLOYMENT.md. Do not assume production is deployed.
- Follow repository contribution guidance. Ask only
  for missing information that materially affects the work. New external services
  and public-data providers must be discussed before integrating them.

## Product intent and workflow

The user wants to know total wealth, asset allocation, liquidity and why wealth changes.
Updates are irregular, roughly quarterly; older history is annual with some interim
dates. Track values at explicit dates and support saving/resuming partial drafts.
Keep missing observations distinct from zero. Show dates when carrying values forward.

Use a calm, compact financial dashboard with a dark default and optional light mode.
English is the default language; honor explicitly saved Dutch/English and theme choices.
Browser language and OS color preference do not override these defaults.
The main figure is net private-equivalent wealth including home and pension, each
toggleable. Important charts: annual stacked private/home/business/pension bars,
liquidity, asset allocation and a change-explanation waterfall.

All user-facing screens, validation and chart labels must support Dutch and English.
Use locale-appropriate numbers/dates and EUR reporting. Account names remain user data.
Desktop is primary; keep layouts usable on mobile. A separate instance is acceptable
for the spouse's separate data. All authenticated users within one instance share
the same portfolio; authentication does not provide tenant isolation.

## Agreed financial semantics

- Only the joint private bank account is shared: enter the full balance, count 50%.
  All other assets belong fully to the user.
- Account values are authoritative. Allocation uses account-level classification.
  Individual-position workflows are removed; existing position data remains archived.
- Investment result = account value - net deposits since opening (all deposits minus
  all withdrawals). Both inputs in EUR; blank remains unknown, zero/negative are valid.
  Total result is available on the first observation. No return percentages, flow modes
  or comparison baselines. Period gains use differences between consecutive known
  net-deposit observations; missing endpoints stay unexplained.
- Internal transfers are not total-wealth growth. Unexplained differences remain visible.
- Loans and deposits share the interest-bearing-claim model. The personal loan is money
  lent out. Deposits can have different rates/maturities. Principal repayment is not income.
  Interest must be entered once, on the account that earned it.
- Home = full estimated property value plus negative mortgage balances.
  Report equity and LTMV. Gross asset-allocation charts exclude debts and tax corrections.
- Pension is a separate attribute, not an exclusive investment asset class.
- The closed consultancy was a sole proprietorship. Holding is owned directly, operating
  company through Holding; both companies are fully owned and form a fiscal unity.
  Count underlying accounts once, without also counting participation/intercompany values.
- The simplified example liquidation assumptions are 26.9% AB and 19% VPB:
  bank AB = -business bank balances * AB;
  broker VPB = -(broker value - tax basis/net contributions) * VPB;
  broker AB = -(broker value + VPB correction) * AB.
  Losses intentionally produce a positive VPB correction in this scenario.
  These are user assumptions, not a promise of legally current tax rates.
- Preserve imported historical tax corrections. Changing balances does not automatically
  rewrite those corrections.

## History and privacy

The example importer is verified using fictional fixtures.
The malformed final header '€ 12.345' was explicitly confirmed as 2025-08-01.
Its displayed whole-euro values can leave small rounding differences in totals.
Recalculate derived liquidity breakdowns from recorded inputs.
Missing historical joint account balances remain unknown.
Historical cash flows and individual positions are unavailable.

The dedicated importer currently recognizes the agreed Overview layout. It preserves
historical values/adjustments, rejects duplicate files/dates and does not retain uploads.
Consultancy closure is currently inferred as 2024-01-01 (first absent source date);
a more precise closure date can be configured later.
When splitting historical aggregate Example Deposit Provider into individual deposits, close the aggregate
on the first detailed date so both representations are not counted together.

Do not commit real financial values, exports, databases, backups, credentials or .env.
Use fictional fixtures and demo data. Do not copy private source data into documentation,
screenshots, tests or CI logs. The project mirror's sources/ and synced files are read-only.
Google is an accepted provider, R2 was mentioned as an optional future backup destination,
and other cloud providers need discussion. No external data service is configured now.

## Architecture and navigation

- Python / Django 5.2 LTS, SQLite, Django templates + HTMX, Apache ECharts.
- Docker Compose: compose.yaml plus compose.dev.yaml or compose.prod.yaml.
- Local development: localhost:8000; production: user's existing Traefik frontend.
- SQLite lives on a local persistent volume. Do not put the active DB on R2 or NFS.
- config/: settings, URLs and WSGI. Production requires DJANGO_SECRET_KEY.
- wealth/models.py: owners, accounts, dated observations, positions, tax corrections.
- wealth/services.py: calculation/reporting logic, independent of templates.
- wealth/forms.py and views.py: input validation and authenticated UI workflows.
- wealth/importer.py: Overview-specific, atomic historical import.
- wealth/management/commands/: demo seed, import and online SQLite backup.
- templates/, static/: UI. Libraries are vendored with licenses; no runtime CDN requests.
- locale/nl/: Django gettext .po and compiled .mo. English is the source language.
- tests/test_tally.py: fictional calculation, import, validation and view tests.

Store money as integer cents and calculate with Decimal (half-up rounding).
Money display/input defaults to whole amounts. The top-bar preference enables cents
and is saved per browser/instance. Unchanged rounded fields preserve stored precision.
Optional exact quantities/prices use decimal strings, not SQLite REAL arithmetic.
Keep migrations in Git and calculation rules explicitly tested.

## Development and verification

Local Docker via Make:
    make up TALLY_INSTANCE_NAME=tally-dev
    make demo TALLY_INSTANCE_NAME=tally-demo TALLY_DEV_PORT=8002
    make login TALLY_INSTANCE_NAME=tally-dev
    make down TALLY_INSTANCE_NAME=tally-dev

Make startup applies migrations and prints the URL plus a persistent, randomly
generated development login (DEBUG only). Credentials live in the instance volume
at /data/.dev-login.json with mode 600; never commit or include them in logs/screenshots.
Use the same instance name and optional TALLY_ENV_FILE on subsequent commands.
Demo seeding only accepts an empty portfolio. Existing credentials are never reset.
See README.md for ports, cookie isolation and all Make targets.

Local Docker without Make:
    docker compose -p tally-dev -f compose.yaml -f compose.dev.yaml up --build -d
    docker compose -p tally-dev -f compose.yaml -f compose.dev.yaml exec app python manage.py createsuperuser

Use seed_demo only in an empty, disposable portfolio. The existing local Docker
instance was created with fictional demo data; inspect current state before seeding.
Do not reset volumes or credentials merely to recover a development session.

Without Docker:
    python3 -m venv .venv
    .venv/bin/pip install -r requirements-dev.txt
    DJANGO_DEBUG=1 .venv/bin/python manage.py migrate
    DJANGO_DEBUG=1 .venv/bin/python manage.py runserver

Required checks for application changes:
    .venv/bin/pytest -q
    .venv/bin/python manage.py makemigrations --check --dry-run
    git diff --check

Run relevant browser checks for UI changes and Docker builds when deployment inputs
change. Do not rerun unrelated tests for documentation-only changes.
Translate new strings, then compile without traversing the virtual environment:
    DJANGO_DEBUG=1 .venv/bin/python manage.py makemessages -l nl --ignore=.venv --ignore=static/vendor
    DJANGO_DEBUG=1 .venv/bin/python manage.py compilemessages --ignore=.venv

Initial application validation: 29 tests passed; Docker build/dev startup and
NL/EN UI were checked; fixture CSV import and SQLite backup restore were verified in
a disposable database. Initial commit a37d36d passed GitHub Actions.
Check current CI rather than treating this historical result as current verification:
    gh run list --repo OWNER/REPOSITORY --limit 5

## Known boundaries and next work

- Production host/network/certificate settings still need to come from the user.
- Public market-data updates are a later feature. Choose a provider with the user;
  preserve historical observations and label price source/time.
- No per-trade performance, ETF look-through, bank sync or automated tax filing.
- Classification and ownership are currently account-level settings: changing them can
  reinterpret past reports. Add versioning if historical changes become a requirement.
- Issue #13 supersedes #3. Migration 0005 converts active inception counters and
  backfills imported Example Brokerage Value from the Overview importer's Example Brokerage Contributions/basis field,
  confirmed by the user as inception net deposits. Other tax bases and period-only
  totals do not imply inception flows. Old inputs remain stored; net deposits edit
  independently of tax basis. Historical tax corrections are never rewritten.
- CSV export covers observations; a full SQLite backup is required for positions,
  configuration and login data.
- Further decisions are recorded in docs/decisions.md. Update this handoff when a
  substantive decision or operational assumption changes.

## Local instances prepared for review

- Demo: Compose project tally-dev, http://localhost:8000, fictional data.
- Real-data development: project tally-local, http://localhost:8001, using ignored
  .env.local with a unique secret and distinct session/CSRF cookie names.
- Restart the real-data instance with:
      docker compose --env-file .env.local -p tally-local -f compose.yaml -f compose.dev.yaml up -d
- Development uses fictional data. Never seed
  this database or reset its volume. Inspect current state before importing again.
- No production-server deployment is implied by this local real-data instance.
- Draft valuations can be deleted from the list or editor after a translated confirmation.
  Deletion requires an authenticated CSRF-protected POST and removes associated
  observations, archived positions and tax adjustments. Published valuations are protected.

- Issue #19: ordinary editor saves cannot demote published valuations. Missing or
  unknown actions are rejected without mutation; stale draft submissions preserve
  publication and its validation. Published editors expose Save only.

- Issue #20: editor submissions require the signed editor_version rendered by GET.
  Stale submissions return HTTP 409, preserve entered values and offer latest saved
  values for reconciliation. Reload and re-enter changes; never refresh the token
  on a rejected or invalid bound form. SQLite IMMEDIATE transactions serialize the
  check with saves, publication and deletion. No schema change is required.

- Issue #21: missing company-broker tax basis leaves broker deductions and net
  totals unknown unless both snapshot-level broker tax overrides are recorded.
  Gross reporting remains available. Publishing checks carried values and imported
  snapshots; historical overrides are preserved. Coverage warnings appear on the
  dashboard, analysis and editor; incomplete net comparisons are unavailable.
