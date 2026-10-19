# Using Tally

This guide describes the behavior and data conventions exposed by Tally. For a
concise product contract, see the [product specification](product-spec.md).

## Portfolio and valuation workflow

Add owners and accounts, then start a valuation on any date. Enter full EUR
balances: a joint bank account counts at 50%, other assets follow recorded
ownership, and mortgages are negative. Save a draft or publish it. A blank means
unknown, not zero. Older available observations retain their original observation
date and are flagged when carried forward. Closed accounts disappear on and after
their closing date, while earlier history remains.

For investment accounts, enter the account value (including cash) and net deposits
since opening: deposits minus withdrawals, in EUR. Total gain/loss is account value
minus net deposits, available from the first observation. Blank net deposits mean
unknown; zero and negative values are valid. Deposits and withdrawals do not change
gain/loss without investment movement. Tally does not require flow modes, comparison
baselines, trade history, or individual positions. Allocation uses the account's
asset class. Older position data remains archived. Company accounts have a separate
tax-basis input for the liquidation scenario.

Only underlying company accounts are valued; do not add participation value on top
of subsidiary assets. Sole-proprietor assets are not classified as Box 2.

## Currency, precision, and account deletion

Balances, tax bases, net deposits, interest, reports, and observation exports are in
EUR. Account currency is legacy metadata and does not convert observations. New
accounts and currency changes use EUR; existing non-EUR metadata is retained as-is.
Tally performs no automatic foreign-exchange conversion.

Set `TALLY_MONEY_PRECISION=whole` (default) or `cents` per instance to control
display and input precision for every browser using it. Stored values and
calculations always retain exact cents.

An account can be deleted only when every dated financial value and archived
position is zero or unknown. Any non-zero historical value blocks deletion and the
affected valuation dates are shown. Safe deletion removes the account's observations
and archived positions, while preserving shared valuation snapshots and tax
adjustments.

## Historical CSV import

Use Import history to preview the supported Overview CSV, then select it again and
confirm. Preview shows recognized, ignored, and missing rows; per-date
reconciliation; and configuration conflicts. Every supported account row is
required, even when historical cells are blank. Basis, tax, and liquidity rows are
optional. Each date needs a source total and a recognized balance. Differences over
EUR 2 block import until corrected. Existing account classifications and date
boundaries must be compatible; user settings are never overwritten. Duplicate
dates/files are rejected atomically.

Example files and mappings use fictional labels and values. A malformed sample
amount header maps to a sample valuation date. Example business closure metadata
uses a fictional date and can be configured for another dataset. A new joint
account receives no invented historical balance. CSV values are rounded displayed
euros, so small differences from source totals can remain.

The designated fictional brokerage contributions row supplies net deposits and
remains separate from tax basis. Net deposits for other investment accounts remain
unknown. Uploaded files are not retained. Historical imports preserve tax
adjustments/source totals and recalculate chart breakdowns. The CLI supports a
preflight preview and an explicit apply:

```sh
python manage.py import_overview /path/to/Overview.csv
python manage.py import_overview /path/to/Overview.csv --apply
```

`TALLY_IMPORT_HISTORY_ENABLED=0` hides the import navigation and empty-dashboard
action, makes direct `/import/` requests return 404, and disables the
`import_overview` management command. The default is `1`; recreate the app after
changing it.

## Calculation conventions

Money is stored in integer EUR cents. Calculations use Python `Decimal` with
half-up rounding. Optional exact quantities and prices are stored as decimal
strings, avoiding SQLite floating point values.

- Total investment gain/loss = account value − net deposits since opening.
- Period gain/loss = change in account value − change in net deposits, using
  consecutive known observations. Tally shows no timing-adjusted or annualized
  percentage.
- Example bank AB = −company bank balances × AB rate.
- Example broker VPB = −(value − tax basis) × VPB rate.
- Example broker AB = −(value + VPB adjustment) × AB rate.
- The example rates are 26.9% AB and 19% VPB. A loss produces a positive VPB
  correction. These are assumptions, not statutory tax advice.
- Imported historical tax corrections take precedence and remain unchanged when
  associated balances are edited.
- Net wealth deducts mortgages and scenario tax. Allocation shows gross assets.
  Liquidity includes mortgages but displays tax separately. Allocation uses
  account-level classification.
- Account flows explain account return, not household income or spending. Internal
  transfers are not total-wealth growth.

## Change analysis

The waterfall reconciles consecutive published valuations using matching-period
account results, explicitly entered bank/claim interest, property revaluation, and
tax-correction changes. Remaining income/spending, missing flows, mortgage principal
movements, and changes in coverage stay in Other / unexplained.

Enter interest once, on the earning account, as a period amount rather than a
cumulative total, with explicit dates ending on the valuation date—even when the
interest was paid into another tracked account. Older undated amounts remain stored
but cannot be assigned to a period. Expand each change category to inspect account
contributions, opening/closing values, and observation dates. Unexplained
contributions show missing flows and changes in account coverage, sorted by
magnitude; offsetting transfers remain visible even when the category total is zero.
Snapshot-wide tax corrections are grouped by correction type instead of being
allocated to individual accounts.

Analysis also shows a previous-year wealth bridge. Its baseline is the latest
published valuation on or before the same calendar date one year earlier (February
29 uses February 28); both actual dates appear. Investment results require actual
observations and known net deposits at both dates. Interest is attributed only when
recorded published periods cover the full comparison without gaps. Missing baselines
and incomplete endpoints show an unavailable state.

## Investment history migration

The migration for the investment simplification converts active, complete inception
deposit/withdrawal counters to signed net deposits. It also backfills imported
fictional brokerage-value observations from the importer's fictional brokerage
contributions field (stored as basis). This mapping applies only to that designated
source; other tax bases and period-only flows are not treated as inception net
deposits. Legacy flow inputs, positions, and tax corrections remain stored. Ordinary
editing changes net deposits independently of tax basis. CSV export includes
`net_deposits_eur` and preserves legacy columns for recovery.

## Backup and restore

Use Django's SQLite online backup API, not a file copy of an active database:

```sh
docker compose -p tally-prod -f compose.yaml -f compose.prod.yaml exec app \
  python manage.py backup /backups/tally-2026-10-11.sqlite3
```

Backups are private (mode 600) from creation, never overwrite existing paths, and
are cleaned up on failure. Copy them out with `docker compose cp` and your encrypted
off-host backup process; Tally configures no external backup service.

Restore while the app is stopped: preserve the existing volume, replace
`/data/tally.sqlite3` with the verified backup, remove stale `-wal`/`-shm` companions
for that stopped database, preserve ownership `10001:10001`, then restart and
verify. Test restoration in a separate Compose project first. Backups contain login
and financial data. CSV export is portable observation data, not a full backup.
The [production guide](../DEPLOYMENT.md#6-backups) contains the full operating
procedure.
