# Tally product specification

This document describes the current product contract for Tally. Use it to preserve
behavior when implementing features or changing the interface. The issue and pull
request history informed this summary, but older proposals are not requirements when
they conflict with this specification, `AGENT.md`, or the detailed decisions in
[`decisions.md`](decisions.md). Update the product contract when an agreed behavior
changes.

## Purpose and operating model

Tally is a self-hosted record of a portfolio's wealth over time. It helps an owner
understand total wealth, liquidity, asset mix, and the reasons wealth changed. Entries
are dated snapshots made intermittently; the application must not assume continuous
tracking or fill historical gaps with guesses.

Each running instance contains one shared portfolio. Authentication controls access;
it does not isolate data between users. Use separate instances and storage for
separate portfolios. Reports use EUR. The interface supports English and Dutch, with
English and dark mode as first-visit defaults. Saved preferences take precedence.

## Portfolio and valuation behavior

- A portfolio contains owners and accounts. Accounts have an owner, account-level
  classification, and applicable start, maturity, and closure dates. Values are
  recorded at explicit observation dates within draft or published valuations.
- Drafts can be partial and resumed. Missing values mean unknown, not zero. Reports
  show the date of a carried-forward observation. Publishing validates the submitted
  values and any effective carried-forward values required by the report.
- The headline is net private-equivalent wealth. Home and pension can be included or
  excluded. Annual reports separate private, home, business, and pension amounts;
  liquidity, gross asset allocation over time, and a valuation coverage matrix are
  also available. The matrix distinguishes observed, carried, missing, and
  lifecycle-inapplicable values without changing calculations.
- Account values are authoritative. Allocation is based on account classification.
  Individual investment positions are not part of the normal entry or reporting
  workflow; legacy position records remain archived and are not counted on top of
  account values.
- The joint private bank account is entered at its full balance and contributes 50%.
  Other assets follow their recorded ownership. Corporate holdings are consolidated
  by counting underlying accounts once, not participation or intercompany values as
  additional wealth.
- A home is the full estimated property value plus negative mortgage balances.
  Reports can show equity and loan-to-market value. Gross allocation excludes debts
  and tax corrections. Pension is a reporting attribute, not an exclusive asset class.
- Loans receivable and term deposits are interest-bearing claims. Principal repayment
  is not income. Different claims can have distinct rates and maturity dates. The
  maturity calendar uses recorded dates and last published balances; it reports
  overdue or unknown cases without inferring repayments or additional interest.

## Investment, interest, and change explanations

- Total investment result is account value minus cumulative net deposits since
  account opening. Net deposits are deposits less withdrawals, in EUR. The result is
  available on the first observation when both values are known. Blank remains
  unknown; zero and negative net deposits are valid. Do not report a return percentage
  from these two totals. Performance net deposits and business tax basis are distinct
  concepts even if a documented source field supplies both values.
- Period investment gain is the change in account value less the change in cumulative
  net deposits between matching, known observations. Missing endpoints or flows remain
  unexplained. Internal transfers do not increase total wealth.
- Interest is recorded once as a period amount on the account that earned it, with
  explicit start and end dates; the end date matches the valuation date. Legacy
  interest without dates remains uncovered. Never infer a period from neighboring
  observations. Attribute interest only when recorded intervals cover the comparison
  exactly.
- Change analysis separates contributions and explains only causes supported by
  recorded observations. Carry-forward dates remain visible, offsetting changes remain
  separate, and unexplained amounts are not assigned to invented transfers or causes.
  Tax-correction movements are described neutrally and do not imply a change in rates.
- Previous-year comparisons use a qualifying published valuation on or before the
  corresponding prior-year date and show the actual endpoint dates. Incomplete
  endpoints or incomplete tax scenarios do not produce a misleading comparison.

## Business tax scenario

Business liquidation adjustments implement a simplified, user-defined scenario, not
legal or current tax advice. The example rates are 26.9% AB and 19% VPB. The scenario
calculates bank AB from business bank balances, broker VPB from value less tax basis,
and broker AB after the VPB correction. A loss can produce a positive VPB correction
under these assumptions.

For clarity, the example calculations are: bank AB = `-bank balance × AB`; broker
VPB = `-(broker value - tax basis) × VPB`; broker AB =
`-(broker value + VPB correction) × AB`. The supported example entity structure may
include a sole proprietorship, a holding, and a fully owned operating company held
through that holding. Count the operating company's underlying accounts once.

Unknown broker tax basis makes the calculated broker deductions and net totals
unknown unless the required snapshot-level overrides establish both deductions.
Overrides apply to their snapshot. Imported historical tax corrections are preserved
when balances or account settings change. Do not retroactively recalculate those
historical corrections during ordinary edits.

## Editing, deletion, and historical integrity

- Editing a valuation must preserve the distinction between drafts and published
  history. Ordinary saves cannot demote a published valuation. Published valuations
  cannot be deleted through the draft workflow.
- Valuation forms are protected against stale edits. Validate the submitted version
  against the saved snapshot and account configuration inside the write transaction.
  A conflict must preserve submitted input for reconciliation and must not write it.
- Account deletion checks all dated values and archived positions, not just the latest
  balance. Any non-zero financial history blocks deletion. When dependent values are
  all zero or unknown, remove the account history while preserving shared valuations
  and snapshot-level corrections.
- Ownership and classification are current account settings and may reinterpret
  historical reports. Warn about report impact before changes when published history
  exists; do not imply that historical settings are versioned.

## Import and export

- The historical importer supports a documented example CSV layout. Preview and apply
  use the same validation rules. Reject duplicate or incompatible rows, ambiguous
  number formats, out-of-range amounts, and account configuration conflicts before
  writing. Apply a valid import atomically and retain no uploaded file.
- Historical imports preserve recorded observations and tax corrections. Do not
  invent balances, cash flows, ownership, or source values where the file is silent.
  When detailed accounts replace an aggregate, close the aggregate on the first
  detailed observation date so both are never counted together.
- CSV export preserves recorded observations, entered interest, and coverage dates,
  but is not a full backup. A database backup is required to preserve configuration,
  authentication data, and archived records.

## Interface and accessibility

- All screens, validation messages, and charts support English and Dutch. Use locale
  aware number formatting and the fixed `dd-mm-yyyy` format for account dates.
- Monetary precision defaults to whole amounts and can be configured per instance for
  whole amounts or cents. Hiding cents is presentation/input behavior only; storage,
  calculations, and exports retain exact precision. Preserve stored cents when an
  unchanged rounded value is resubmitted.
- Desktop is primary; layouts remain usable on mobile. Charts provide keyboard
  operation and equivalent semantic tables or details. Dates, unknown values, and
  carried-forward values must remain understandable without color or visual inspection
  alone.
- Keep runtime assets local. Do not add a runtime CDN dependency.

## Security and product boundaries

- Use fictional values and generic provider, institution, and business labels in
  examples, fixtures, screenshots, and documentation. Never commit real portfolio
  exports, databases, backups, credentials, or environment files.
- A disabled portfolio login is safe only behind a trusted authenticating proxy with
  direct origin access blocked. All visitors admitted to that route can access the
  shared portfolio; Django admin retains its own staff authentication and permissions.
- SQLite stays on local persistent storage. Production hostnames, proxy routing,
  certificates, secrets, and operator records belong in private infrastructure
  configuration.
- Tally does not provide bank synchronization, transaction-level tracking,
  security-level look-through, foreign exchange conversion, tax filing, or cloud
  synchronization. External quote sources require explicit approval and must retain
  observation time, source, and history.
