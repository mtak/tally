# Tally project working guide

This file is a compact working guide for an agent making changes in Tally. Read
`AGENT.md` for the full product handoff and `docs/decisions.md` for settled design
decisions; those files remain authoritative when this summary is incomplete.

## What this project has been doing

Tally is a self-hosted, bilingual wealth tracker. Recent work has taken it from a
working dashboard toward a dependable financial record: account-level valuation and
investment results; explainable wealth changes; historical asset-mix and maturity
views; safe CSV import/export and backups; and stronger controls around drafts,
published history, stale edits, deletion, and authentication. The recent issue series
also tightened number/date entry, financial validation, accessibility, and production
smoke checks.

Treat features as extensions to a financial record with explicit dates and provenance.
Never silently fill gaps, reinterpret an unknown as zero, infer a cash flow, or rewrite
historical adjustments to make a new view look complete.

## Before changing code

1. Read `AGENT.md`, `README.md`, and relevant sections of `docs/decisions.md`.
2. Inspect `git status --short` and preserve existing user changes and untracked files.
3. Trace the behavior through the calculation/service layer, form or importer,
   template, translations, and tests as applicable. Keep financial rules out of
   templates and views when they belong in `wealth/services.py`.
4. Check the relevant issue and existing UX before introducing a new rule. Settled
   behavior should not be changed as a side effect of a feature.

## Concurrent work

- Use one Git worktree and branch per independent task. Follow `docs/worktrees.md`
  for setup, isolated Docker projects and cleanup.
- The currently configured Playwright MCP has one persistent browser profile and
  one shared page state. Serialize browser validation between contexts. Parallel
  browser work requires separate MCP server sessions configured with `--isolated`;
  do not assume separate tabs on the shared endpoint provide isolation.

## Financial and data rules

- Store money as integer cents; calculate with `Decimal` and explicit half-up rounding.
  Do not use binary floats for financial arithmetic.
- Blank means unknown; zero and negative values can be meaningful. Preserve actual
  observation dates when carrying values forward and show that date to users.
- Reports are EUR. Account currency is legacy metadata, not an FX conversion request.
- Account values drive reporting and account classification drives gross allocation.
  A joint private bank balance is entered in full and weighted 50%; other assets are
  fully owned unless the recorded ownership says otherwise.
- Investment result is account value minus inception net deposits. Keep net deposits
  separate from tax basis. Do not add return percentages, transaction-level tracking,
  or inferred flows.
- Internal transfers do not create wealth. Keep unexplained changes visible and label
  tax correction changes neutrally.
- Interest is a period amount with explicit start/end dates; the end equals valuation
  date. Legacy undated interest remains uncovered. Attribute it only for an exact
  interval match; never infer coverage from nearby observations.
- Business liquidation adjustments follow the user's simplified assumptions, not
  general tax advice or a claim about current law. Missing company-broker tax basis
  leaves broker deductions and net totals unknown unless both snapshot-level broker
  VPB and AB overrides are recorded. Preserve imported corrections when balances
  change.
- Count underlying company accounts once. Do not add holding/subsidiary participation
  values on top of the underlying assets. Home is property value plus negative
  mortgage; gross allocation excludes debt and liquidation tax. Pension is a separate
  reporting attribute.
- Historical classification and ownership use current account settings. Warn about
  impact before report-affecting edits when published history exists; do not imply
  historical versioning.

## Editing and import safety

- Published valuations cannot be demoted by ordinary saves. Accept only explicit,
  valid actions; protect mutations with CSRF and transactions.
- Editor submissions carry a signed version of the saved state. Validate it inside an
  SQLite IMMEDIATE transaction before writes. On conflict, preserve submitted values
  and the original row mapping; do not refresh the token on invalid or rejected forms.
- Keep draft deletion explicit and protected; published valuations are not deletable.
  Account deletion checks all historical nonzero values and archived positions before
  deleting, and preserves shared snapshots/tax adjustments.
- Overview CSV behavior is deliberately source-specific. Reuse the shared preflight
  for preview and apply; validate identities, row mappings, account compatibility,
  dates, strict Dutch number grouping, reconciliation, and duplicate imports. Apply
  atomically, report row/label/date without echoing private amounts, and never retain
  uploads.
- Do not count an aggregate account and its detailed replacements at once: close the
  aggregate on the first detailed observation date.
- Keep archived position/history data unless a documented migration or explicit
  deletion rule calls for changing it. CSV observation export is not a full backup.

## UI, language, and accessibility

- English and dark mode are first-visit defaults; saved preferences take precedence
  over browser/OS preferences. All screens, validation, chart labels, and new strings
  need Dutch and English support.
- Use locale-aware display formatting, while preserving canonical values in storage
  and exports. Numeric input accepts comma or period decimals in either language and
  rejects ambiguous single three-digit separator forms. Account dates use `dd-mm-yyyy`.
- Whole-euro entry/display is the default; preserve stored cents when a rounded field
  is unchanged. Respect the instance's `TALLY_MONEY_PRECISION` setting.
- Keep desktop compact and mobile usable. Charts need matching semantic tables or
  accessible detail, keyboard operation, actual observation dates, and clear unknown
  or carried-value states. Avoid color as the only signal.
- Vendor runtime assets locally; do not add runtime CDN dependencies.

## Architecture and implementation habits

- Django 5.2, templates/HTMX, Apache ECharts, SQLite, Docker Compose.
- `wealth/models.py`: domain records and constraints; `wealth/services.py`: calculations
  and reports; `forms.py`/`views.py`: validation and workflows; `wealth/importer.py`:
  Overview import; management commands: demo/import/backup; templates and `static/`:
  UI; `locale/nl/`: translations.
- Enforce financial invariants at every supported write path, including forms/admin
  and ORM bulk/queryset writes where relevant. Raw SQL and `save_base` are maintenance
  bypasses, not application APIs. Migrations should audit before constraining legacy
  data and fail safely instead of silently repairing it.
- Keep changes issue-scoped, make error paths recoverable and translated, and update
  `docs/decisions.md` plus `AGENT.md` when a substantive product or operational rule
  changes.

## Privacy and operations

- Use fictional fixtures and demo data only. Never commit real financial values,
  exports, databases, backups, credentials, or `.env` files. Do not put private source
  data in docs, screenshots, tests, or CI logs. The project mirror's `sources/` and
  synced files are read-only.
- There is one shared portfolio per instance; authentication is not tenant isolation.
  Keep real-data and demo instances in separate Compose projects and volumes. Never
  seed, reset, or re-import into the existing real-data instance without an explicit
  task and careful state inspection.
- SQLite must stay on local persistent storage, not R2/NFS. Production routing,
  secrets, hostnames, certificates, and operator records belong in the separate
  infrastructure repository and `DEPLOYMENT.md` workflow, not app-specific config
  committed here.
- No external market-data or cloud service is configured. Discuss a new provider
  with the user before integration. Preserve source/time and historical observations
  if a quote feature is later approved.

## Verification

For every application change, follow `AGENT.md`: run `.venv/bin/pytest -q`,
`.venv/bin/python manage.py makemigrations --check --dry-run`, and `git diff --check`.
UI changes also need relevant Playwright MCP browser validation. Deployment-input
changes need Docker build checks and the production smoke workflow in
`docs/verification.md`.
Documentation-only edits do not need unrelated test reruns. Check current CI with
`gh run list --repo OWNER/REPOSITORY --limit 5`; old green runs are historical evidence only.

Do not reset Docker volumes or credentials as a troubleshooting shortcut. Use
`make help`, specify the same `TALLY_INSTANCE_NAME` for each operation, and seed demo
data only into an empty disposable instance. Production deployment is not implied by
local real-data development.
