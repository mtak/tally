# Tally: conversation handoff and working instructions

## Start here

- Product: Tally, a personal wealth tracker for the personal wealth tracker project.
- Project repository: https://github.com/OWNER/REPOSITORY
- Existing local checkout: /path/to/tally
- ChatGPT project mirror:
  /home/user/.codex/.chatgpt-projects/[local project id]
- Reuse this checkout and inspect git status before editing. Preserve user changes.
- Read README.md, docs/decisions.md, and relevant code before changing behavior.
- Generic production instructions are in DEPLOYMENT.md. Site-specific deployment
  scripts, configuration and operational records belong in a separate private
  infrastructure repository, not this application repository.
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
- Local development: localhost:8000; production: a trusted HTTPS reverse proxy.
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

Use Playwright MCP for browser validation (user preference).
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

- Issue #66: the version label includes the image's short Git SHA (full SHA on
  hover), also visible in the mobile page footer. `TALLY_GIT_COMMIT` is baked into
  the image via a build argument; Make and the production `dc` helper supply the
  checkout revision. Missing metadata shows only the version. Build clean releases
  and keep the image metadata when reusing/rolling back images.

- Production host/network/certificate settings belong to the operator's infrastructure.
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

## Local development instances

- Demo: Compose project tally-dev, http://localhost:8000, fictional data.
- Real-data development: project tally-local, http://localhost:8001, using ignored
  .env.local with a unique secret and distinct session/CSRF cookie names.
- Restart the real-data instance with:
      docker compose --env-file .env.local -p tally-local -f compose.yaml -f compose.dev.yaml up -d
- Development uses fictional data. Never seed
  this database or reset its volume. Inspect current state before importing again.
- No production-server deployment is implied by this local real-data instance.
- Issue #54: `TALLY_AUTH_ENABLED=1` (default) requires portfolio login; `0` delegates
  access control entirely to an authenticating proxy with direct access blocked.
  Other values fail startup. Portfolio routes keep CSRF and existing validation;
  no proxy identities or users are created. Login redirects to dashboard; POST logout
  redirects without ending sessions and GET remains disallowed. Hide portfolio
  user/sign-out controls, retain precision preferences. Admin still requires its own
  active staff login/permissions; use admin login/logout. See DEPLOYMENT.md for setup.
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

- Issue #46: dashboard asset-mix history uses the same latest published valuation
  per calendar year as wealth history. Positive gross asset-class totals and
  ownership shares match the allocation pie, exclude mortgage/tax, and honor home
  and pension filters. Exact-cents percentages stay available with incomplete net
  tax; zero gross totals are unavailable. Tooltips and the accessible table expose
  actual valuation dates, carried dates and missing observations. Current account
  classifications still apply to historical reports.

- Issue #48: chart bars open and focus the matching category detail table. Tables
  expose explanations separately and support keyboard scrolling on mobile.
  Carried/unknown-deposit rows remain inspectable even with zero contribution.
  Unknown causes stay neutral; tax changes are labeled correction changes.
  Reconciliation, tax coverage and observation-period attribution are unchanged.

- Issue #47: analysis includes gross investment-account history with an account
  selector (including closed accounts), true calendar spacing and a matching
  accessible table. Only actual published observations through the selected date
  appear. Missing inception net deposits break deposits/result lines; zero and
  negative deposits remain valid. Full account results exclude ownership scaling
  and liquidation corrections; historical adjustments remain unchanged.

- Issue #45: Maturity calendar selects a published valuation and uses active claim
  accounts with their last published ownership-adjusted balances. Upcoming quarterly
  gross totals separate private/business funds. Tables preserve carried observation
  dates and expose overdue, unknown maturity, missing balance and nonpositive cases.
  The timeline uses registered start/end dates only. No repayments or extra interest
  are inferred and existing liquidity/tax/valuation calculations are unchanged.
  Current account date metadata also applies to historical calendar views.

- Issues #56–58: numeric UI inputs accept either decimal separator; ambiguous single
  three-digit separator groups are rejected. Input values omit thousands grouping,
  while reports retain locale grouping. Account dates use dd-mm-yyyy with a local
  calendar in both languages. Account overviews/selectors and change-detail groups
  sort by case-insensitive name with primary-key ties. Stale editors preserve the
  submitted row layout. See docs/decisions.md for details.

- Issues #23, #62, #64: observation CSV includes exact entered `interest_eur`.
  Account History lists actual observations, including drafts/imported history,
  newest first, with full values and recorded type-specific fields. No carried
  records are synthesized. Accounts & assets and valuation editor rows use owner
  name/ID then account name/ID ordering; other overviews retain name ordering.
  Global account-name uniqueness and stale editor row/owner mappings remain intact.

- Issues #25/#38: Overview rejects duplicate consumed labels and Prive/Totaal
  structures with translated row locations; irrelevant repeated headings remain
  allowed. Import conflicts are translated and atomic. Malformed editor layouts
  return a normal translated HTTP 400 page with saved rows and reload recovery;
  validate identities/order before binding rows to account labels. Valid stale
  layouts keep HTTP 409 and their signed original mapping and submitted values.

- Issues #33/#61: dashboard annual wealth, allocation and liquidity have semantic
  tables using the same report values as charts. Annual totals use exact report
  cents and actual valuation dates; incomplete net years have no bar/total label.
  Full EUR labels sit above positive stacks, with keyboard horizontal scrolling
  on narrow screens. Home/pension/net, language and precision remain shared.
- Issue #63: Credit card is an account-level asset class. Use Bank account and
  Liquid availability; enter debt negative, settled zero, provider credit positive.
  Existing signed wealth/liquidity and positive-category gross-allocation rules
  apply unchanged; no separate card balance or automatic sign conversion exists.

- Issues #34/#36: dirty valuation inputs require leave confirmation for preferences,
  links and sign-out; browser unload covers back/reload/close. Rejected inputs remain
  guarded and successful saves reset the baseline. No automatic recovery/conversion.
  Report-affecting account edits with published observations require a signed impact
  review bound to current/proposed settings. Current metadata still reinterprets
  history; observations/imported corrections stay unchanged, without versioning.


- Issues #32/#37/#39: backup uses a private exclusive temporary file and atomic
  no-clobber publication on local storage, with failure cleanup and explicit closes.
  Production routing uses validated `TALLY_TRAEFIK_ID` (default `tally`); each routed
  instance needs a unique ID. CI reuses its built image for disposable production
  startup, authenticated HTTP/static checks and fictional file-backed backup/restore.
  Run `python tests/production_smoke.py IMAGE` after building; no existing volumes or
  production deployment are involved. See docs/verification.md and DEPLOYMENT.md.

- Issues #26/#27: shared Overview preflight powers web/CLI preview and atomic apply.
  All mapped account rows are required (historical blanks allowed); basis/tax/liquidity
  rows remain optional. Each date needs a recognized balance and source total;
  source/detail differences above EUR 2 block import. Preview exposes recognized,
  ignored and missing rows, reconciliation and configuration errors. Reused account
  classifications, EUR currency and actual observation lifecycle boundaries must
  match; safe custom metadata stays unchanged. Existing owner parents are validated,
  never overwritten. Confirmed header correction and historical tax rules remain.

- Issues #28/#29: shared financial validation guards forms/admin and ORM saves,
  queryset updates and bulk writes, with atomic rejection. Mortgage balances must
  be nonpositive; ordinary assets nonnegative; credit-card balances stay signed.
  Net deposits, basis, interest and historical tax corrections remain signed.
  Overview uses strict Dutch grouping and explicit half-up cent rounding with
  signed 64-bit storage checks, reporting row/label/date without echoing amounts.
  Migration 0008 audits historical ownership, dates, rates, signs and money storage
  before adding local constraints; incompatibility stops without repairing data.
  Raw SQL/save_base are maintenance bypasses, not supported financial write APIs.

- Issues #24/#59: all observations and reporting are EUR; account currency is legacy
  metadata and never triggers conversion. New accounts/currency changes require EUR;
  existing non-EUR metadata is preserved unchanged. Account deletion is an atomic,
  CSRF-protected POST and is blocked by any nonzero historical financial value or
  archived position, with affected dates shown. Safe deletion removes account-owned
  observations/positions while preserving shared snapshots and tax adjustments.
