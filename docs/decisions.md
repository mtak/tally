# Product and architecture decisions

- One self-hosted portfolio per instance. Dutch and English, EUR reporting.
- English and dark mode are the first-visit defaults, independent of browser language
  and OS color preference. Explicit language cookies and saved theme choices take
  precedence. Initialize the theme before rendering; unavailable storage falls back
  to dark mode. Dutch and light mode remain available in the existing controls.
- Owner types: private, sole proprietor and company; holding/subsidiary metadata.
  Underlying assets are counted once. A shared private bank account counts at 50%.
- Any valuation date, draft/resume workflow, explicit observation dates, blanks not zeros.
- Whole-account gain/loss from account value minus net deposits since opening.
  No percentage return or individual trade input.
- Account classification determines allocation; account value is authoritative.
  Individual position workflows have been removed; existing data stays archived.
- Loans and term deposits use one interest-bearing-claim model with individual rates
  and maturity dates. Claims are separate accounts, so each can be valued independently.
- Interest amounts are period flows, not cumulative-to-date totals. Store each with
  explicit start and end dates; the end date must equal its valuation date. New
  amounts cannot be saved without both dates. Existing amounts
  retain null dates and are treated as uncovered: no period may be inferred from
  neighboring valuations. Interest attribution requires exact equality between its
  recorded interval and the comparison endpoints. The old amount remains available
  in account history and CSV export.
- Previous-year comparisons use the latest published valuation on or before the same
  calendar date one year before the selected valuation (Feb 29 maps to Feb 28 in a
  non-leap year). Screens show the actual endpoint dates. The comparison is unavailable
  when there is no qualifying baseline or either endpoint is incomplete. Investment
  attribution requires actual observations for that account at both endpoints; interest
  contributes only when published, recorded intervals cover the comparison exactly.
  Consecutive interest intervals may tile the full span; gaps and undated amounts stay
  unexplained. The analysis page shows this bridge beside the consecutive-period bridge.
- Home equity and pension are included by default and can be excluded.
- Business tax rules reproduce the agreed personal liquidation scenario; they do not
  automatically follow statutory rates. Imported historical adjustments are preserved
  through ordinary valuation editing.
- CSV history contains aggregate balances. To replace an aggregate (for example Example Deposit Provider)
  with individual deposits, close the aggregate on the first detailed valuation date,
  and record the individual deposits from that date. Do not keep both active.
- SQLite on local persistent storage; amounts in integer cents, Python Decimal math.
  Application modules separate models, calculations, import and views.
- Docker Compose development exposes localhost:8000 without Traefik. Production joins
  the existing Traefik network and relies on its TLS setup.
- All runtime assets are local. Public market data will be a separate optional adapter
  after choosing an acceptable provider. A future quote needs instrument identity,
  exchange, currency, quantity, quote time and source; observations remain historical.
- No banking APIs, portfolio look-through, tax filing, cloud sync or external analytics
  in the first version.

## EUR-only observations (#24)

- Account balances, tax bases, net deposits, interest, reports and observation exports
  are EUR. Account currency is legacy metadata; it never converts or relabels a value.
- New accounts and currency changes must use EUR. Existing non-EUR metadata remains
  unchanged and can be retained while editing an account; its observations remain
  interpreted as EUR. No FX calculation or new data provider is introduced.

## Safe account deletion (#59)

- Account deletion is an authenticated, CSRF-protected POST. Check every dated
  observation and archived position within the same transaction as deletion.
- Any non-zero balance, basis, net deposits, interest, legacy flow amount or archived
  position value blocks deletion; the message lists the affected valuation dates.
  A newer zero observation cannot conceal older non-zero history.
- If all dependent financial values are zero or unknown, remove the account's
  observations and archived positions. Preserve shared snapshots and their
  snapshot-level tax adjustments.

## Follow-up improvements

- Review the real-data dashboard after import and splitting aggregate deposits.
- Automated quote adapters, with source approval and immutable valuation history.
- Versioned classification/ownership changes if historical reinterpretation is needed.
- More flexible imports and a full portable JSON export.

## Upstream authentication (#54)

- `TALLY_AUTH_ENABLED` accepts only `1` (default) and `0`. Disabled mode bypasses
  only portfolio login checks and keeps all request/CSRF checks and shared-portfolio
  semantics. No identity headers, synthetic users or staff privileges are introduced.
- Login redirects to the dashboard; POST portfolio logout is a redirect without
  session changes, GET remains disallowed. Hide portfolio user/sign-out controls
  while preserving amount precision. Upstream logout belongs to the access gateway.
- Django admin always uses its own staff login, permissions and logout. Operators
  must secure every route upstream and prevent origin/proxy bypass before disabling
  portfolio authentication. Compose defaults to enabled in all environments.

## Historical asset mix (#46)

- Use the latest published valuation in each calendar year up to the selected
  valuation, matching wealth history. Do not fill years without valuations.
- Percentages use exact ownership-adjusted cents and the positive asset-class
  totals used in the gross allocation pie. Mortgages and liquidation tax are
  excluded; home and pension follow the dashboard filters. An empty denominator
  leaves the distribution unavailable, even when there is debt.
- Keep gross mix available when net liquidation tax is incomplete. Show actual
  valuation dates, carried observation dates and missing observations in the
  accessible table and chart tooltips; round only at presentation.
- Current account classifications also reinterpret historical mix. This feature
  does not introduce classification versioning.

## Investment entry (#13, supersedes #3)

- Each dated investment observation needs only account value and signed cumulative
  net deposits since inception. All deposits minus all withdrawals, in EUR.
- Total gain/loss is account value minus net deposits; no earlier valuation needed.
  Missing net deposits remain unknown; explicit zero and negative totals are valid.
- Changes in account value minus changes in net deposits explain period investment
  gains in the wealth bridge when consecutive observations have matching dates.
  Unknown endpoints stay unexplained; no estimated return percentages are shown.
- The user confirmed Example Brokerage Contributions is inception net deposits. Import and migration map
  that specific source field into net deposits independently of its tax-basis use.
  Active cumulative counters migrate to their signed difference. Period-only totals
  do not establish lifetime net deposits and remain archived, without invented totals.
- Tax basis and imported tax adjustments stay independent of performance inputs.
- Position routes, forms and views are removed. Allocation uses account classification.
  Existing positions and legacy flow inputs remain stored. Observation CSV exports
  include legacy flow inputs, net deposits and entered interest, but omit positions,
  tax adjustments, configuration and login data; use a full SQLite backup for those.

## Amount precision (#7)

- Show and enter whole currency amounts by default, with a persistent browser preference
  in the top bar to enable cents. The preference is isolated by instance cookie name.
- Round display half-up; retain integer cents in storage and exact calculation/export.
  Saving an unchanged rounded input preserves its original precision. Editing it to
  a different whole amount replaces that value. Optional quote prices follow this
  preference; enabling cents restores their existing higher precision. Quantities
  and percentages retain their own precision.

## Locale boundaries (#14)

- UI numbers follow the selected language: Dutch `1.234,56`, English `1,234.56`.
  Numeric inputs accept either comma or period as the decimal separator in either
  language (#56). A single separator followed by three digits with one to three
  leading digits is rejected as ambiguous (for example `1,234` and `1.234`). Enter
  `1234` or `1234.00` for thousands. Explicit grouped decimal forms (`1,234.56` or
  `1.234,56`) and multiple valid groups are accepted. Malformed groups are rejected.
  Input values omit thousands grouping and keep the locale decimal separator;
  overview amounts retain locale grouping. Whole-amount mode still requires whole
  values and preserves stored cents when an unchanged rounded input is saved.
- Reuse Django locale formats and Intl.NumberFormat; no additional dependency.
  Stored cents, Decimal calculations, canonical exports, archived exact position
  values and the Overview importer's explicit Dutch source format stay independent
  of UI language. Whole-amount saves retain unchanged stored cents.

## Published valuation protection (#19)

- Ordinary valuation saves never reopen published history. Draft submissions from
  stale forms also preserve published status and publishing validation.
- Only explicit draft/publish actions are accepted; missing or unknown actions
  cannot change observations or status. Published editors offer Save and no draft
  or delete action. Reopening history would require a separate agreed workflow.

## Concurrent valuation editing (#20)

- Valuation editors carry a signed digest of the saved snapshot, observations, tax
  adjustments and account configuration. Verify it inside the SQLite IMMEDIATE
  transaction before writing any submitted values. Blank rows are part of the state.
- A stale, missing or invalid token returns a translated conflict response without
  saving. Keep submitted inputs and the original row layout visible; show the latest
  saved values with cents and offer a separate tab to reconcile against current data.
- Keep a rejected form's token unchanged: retrying must never authorize an overwrite.
  Reload the editor and re-enter reconciled changes. Deletion never recreates a
  valuation from an old form. Whole-amount precision preservation only runs for a
  matching saved state. This check does not introduce a full revision-history store.

## Liquidation tax coverage (#21)

- Unknown company-broker basis makes both calculated broker deductions unknown.
  Snapshot-level broker VPB and AB overrides can supply those deductions, including
  explicit zero; an unrelated bank override or only one broker override cannot
  establish a complete scenario. Imported adjustments remain unchanged.
- Incomplete scenarios retain gross account values, allocation and liquidity, but
  show no net total, total tax, net business value or net Box 2 value. Net history
  omits incomplete bars, and comparisons require complete tax at both endpoints.
  Dashboard, analysis and valuation editors expose coverage warnings.
- Publishing and editing published valuations validate submitted observations or
  their effective carried-forward predecessors, including imported snapshots.
  Drafts can retain unknown basis. Overrides apply only to their own snapshot.

## Historical tax overrides and broker rounding (#30)

- Each snapshot-level correction replaces the calculated portfolio total for its
  correction type. With known broker bases, a VPB override is the effective total
  broker VPB correction. If broker AB is not overridden, calculate it on the sum of
  broker values plus that effective VPB correction, rounding once at portfolio level.
- Without a VPB override, retain the existing per-broker calculation and rounding
  of AB. An AB override is preserved verbatim regardless of VPB. When any active
  broker basis is unknown, broker deductions remain unknown unless both broker
  corrections are overridden. A complete imported override set remains verbatim.
- Tax movements remain portfolio-level rows by correction type. Label them as a
  tax correction change and do not attribute them to accounts or imply a rate change.

## Inspectable change analysis (#48)

- Chart bars open the corresponding category and focus its keyboard-operable
  summary. Each category has a scrollable table of ownership-adjusted opening/
  closing values, actual observation dates, contributions and explanations.
- Keep zero contributions visible when observations are carried or net deposits
  are unknown, so a zero category total does not hide incomplete attribution.
  Offsetting changes remain separate rows; no transfer is inferred from balances.
- Unknown causes remain unexplained. Tax correction changes use a neutral label;
  they do not imply that the assumed rates changed. Calculation and reconciliation
  rules, incomplete-tax comparisons and the mutation-only chart scale are retained.

## Investment account history (#47)

- Analysis offers an investment-account selector, including closed accounts, and
  value, inception net deposits and total result on actual published observation
  dates through the selected valuation. Do not synthesize carried observations.
- A continuous time axis preserves irregular spacing. Markers identify observations;
  straight connecting lines are visual guides, not measurements between dates.
  Unknown net deposits break both the deposits and result series. Zero and negative
  deposits are valid; the first known observation already has a total result.
- Show full gross account amounts, before ownership shares and liquidation tax,
  alongside a matching accessible table. Honor language and cents preferences.
  Historical adjustments are never changed by this read-only view.

## Claim maturity calendar (#45)

- Select a published valuation and include active claim accounts using the same
  start/closure rules as wealth reporting. Carry only the last published balance
  through that date and retain its observation date. Closing a historical aggregate
  excludes it when its detailed replacements become active.
- Indicative quarterly release uses positive ownership-adjusted gross balances with
  maturity on/after the selected valuation. Private and business amounts are separate;
  business funds are before liquidation tax and are not automatically private funds.
- Past maturities with positive balances require attention, not an inferred repayment.
  Unknown maturities, missing balances and nonpositive balances stay visible in
  separate tables and do not contribute to upcoming quarterly totals.
- The term chart uses only registered start/end dates, with a single marker when just
  one date is known. Undated claims remain in the accessible tables. No principal-only
  balance, repayment schedule or additional interest is inferred. The view never
  changes observations, interest, repayments, tax corrections or liquidity reporting.
- Current account metadata applies to historical calendar views, as with existing
  classification reporting; there is no historical agreement-version store.


## Account entry and ordering (#57, #58)

- All account start, maturity and closure inputs use fixed `dd-mm-yyyy` in both
  languages, independent of browser/OS locale. Text entry works without JavaScript;
  a local calendar uses the same format with translated month names and controls.
  Dates remain canonical date values in storage. Valuation dates are unchanged.
- Account overviews and selectors use case-insensitive name ordering and primary key
  as a stable tie-breaker. Existing calendar/change categories stay grouped, with
  account names ordered within each category. Tax corrections keep their own order.
  Renames take effect on the next load. Rejected stale editors retain the original
  submitted row layout to protect account-to-value reconciliation.

## Read-only account inspection (#23, #62, #64)

- Account history lists actual recorded observations, newest first, including drafts
  and imported history. Full account values are shown without ownership scaling,
  carried-forward records or calculated interest. Current account type determines
  which recorded detail columns appear. Blank remains unknown; zero is explicit.
- Accounts & assets and valuation editor rows group by case-insensitive owner name,
  then owner ID, case-insensitive account name and account ID. Other overviews retain
  alphabetical account ordering. Global account-name uniqueness is unchanged.
  Stale editor submissions keep their signed original row layout and owner labels.
- CSV `interest_eur` preserves blank, zero, sign and exact cents regardless of UI
  language or precision; `interest_period_start` and `interest_period_end` preserve
  coverage, including blanks for ambiguous legacy amounts. Observation export is not
  a full database backup.

## Overview ambiguity and recoverable errors (#25, #38)

- Reject repeated consumed account, basis, tax and liquidity labels, and repeated
  Prive/Totaal structures before building observations. Errors identify the label
  and both CSV row numbers; irrelevant repeated headings remain supported.
- Import configuration conflicts use translated messages with unchanged owner/account
  names and remain atomic. Recoverable import failures stay on the import form.
- Malformed editor identities, row order and management counts return a translated
  HTTP 400 in the editor, with saved values and a reload link. Untrusted row values
  are not paired with account labels. Valid stale layouts retain their signed row
  mapping, submitted inputs and HTTP 409 reconciliation behavior. Invalid actions
  also render in the editor with HTTP 400; no rejected request writes data.

## Dashboard access and card classification (#33, #61, #63)

- Annual wealth, gross allocation and liquidity expose semantic, keyboard-accessible
  tables using existing report data. Wealth labels use the report total, anchored
  above positive stacks even with negative categories. Horizontal chart scrolling
  reserves room for full localized EUR labels on mobile. Incomplete net totals stay
  unavailable. The category legend preserves the full stack to match its total.
- Credit card is an asset class with signed balances, normally a liquid bank-type
  account: negative means owed, zero settled, positive means provider credit. Reuse
  existing signed wealth/liquidity and positive gross-category allocation rules.
  No financial calculation or historical balance is rewritten. Observation CSV
  retains signed values; it does not currently export asset classifications.

## Unsaved inputs and historical configuration (#34, #36)

- Valuation editors compare editable values with their initial rendered values.
  Preference changes, same-tab links and sign-out require confirmation when dirty;
  browser back/reload/close use the browser's leave warning. Cancelling preferences
  restores the selector and keeps entered text. Rejected submissions remain guarded;
  successful saves start clean. No input recovery, storage or locale conversion occurs.
- Changing owner, account type, class, joint share, liquidity, pension or lifecycle
  dates on an account with published observations requires a server-side impact
  review. A signed confirmation binds the proposed values and current configuration;
  further edits or concurrent changes require another review. Other edits and
  accounts without published observations save normally.
- Current metadata still applies to all historical reports and maturity calendars.
  Confirmation never rewrites observations or imported tax corrections and adds no
  metadata versioning. Name, notes, currency and rate do not alter report calculations.


## Backup and production isolation (#32, #37, #39)

- Online backups copy into an exclusively created mode-600 sibling temporary file.
  Closed, completed copies are published with a no-clobber hard link; failure removes
  the temporary file. Existing paths and symlink targets are never overwritten.
- `TALLY_TRAEFIK_ID` defaults to `tally` and consistently names the production router,
  explicit router service link and service. Startup validates the identifier; separate
  portfolio instances require distinct IDs as well as projects/hosts/secrets.
- CI reuses one production image and a fictional file-backed database for startup,
  secure authenticated HTTP/static assets, backup and isolated restore verification.
  It creates and cleans up only its own resources and does not deploy the application.

## Overview preflight (#26, #27)

- One read-only preflight serves the web and command-line previews and is rerun
  inside the atomic apply transaction. It rejects duplicate files/dates and
  incompatible layouts or existing configuration before creating any records.
- The supported Overview requires every mapped account label, including rows whose
  historical cells are blank. Renamed/missing account rows are incompatible. Basis,
  historical tax and source liquidity rows are optional; missing tax deductions
  retain the agreed zero override. Blanks never create account observations and
  explicit zero is an observation. Each date requires a source total and at least
  one recognized balance. The confirmed final header correction is unchanged.
- Preview lists recognized rows with CSV locations, ignored labels, missing required
  and optional rows, and exact per-date source/detail/difference amounts. Differences
  above EUR 2 block import until the source is corrected; ordinary confirmation
  cannot override them. Source liquidity discrepancies remain warnings because
  liquidity is recalculated from account inputs.
- Reused accounts must match owner, type, asset class, liquidity, pension, ownership
  share and EUR currency. Actual observations must be on/after start and strictly
  before closure, matching reporting boundaries. Historical blank cells do not
  require activity on that date. New consultancy defaults are checked too.
- Safe start/closure dates, maturity, rate and notes remain untouched. Existing owner
  types and company parent relationships must match the supported structure;
  import never repairs or overwrites them. This remains an Overview-only importer.

## Consistent financial validation (#28, #29)

- Forms, admin and ordinary/service ORM writes share account ownership/date and
  balance-sign validation. Only private bank accounts can be joint. Mortgages are
  nonpositive, other assets nonnegative, and credit-card debt/zero/provider credit
  remain signed as before. Signed net deposits, tax basis, interest and historical
  tax adjustments remain valid; no automatic sign conversion occurs.
- Monetary storage accepts integer cents in the signed 64-bit range. The Overview
  parser accepts an optional euro prefix and sign (including `-€`), ungrouped digits
  or correct Dutch period thousands groups, and optional comma fractions. Blank
  stays unknown; bare currency symbols, exponents, nonfinite values, misplaced
  whitespace and malformed groups are rejected. Fractional cents round half-up,
  including negative ties; sign validation happens before rounding to zero.
- Model saves validate explicitly; queryset update/bulk writes also validate within
  a transaction. Expression updates and conflict-ignoring bulk writes are rejected.
  Related owner/classification edits cannot invalidate existing ownership/balances.
  Partial saves validate their persisted field combination. Direct SQL, save_base
  and historical migration models are deliberate maintenance bypasses.
- Database constraints enforce local joint-account type, lifecycle date order and
  snapshot assumption ranges. Migration 0008 first audits existing cross-model
  ownership/sign rules and monetary storage too. Any conflict stops the migration
  with record IDs, without logging amounts or rewriting/discarding records. Review
  incompatible history explicitly before retrying. Existing archived positions
  and financial corrections remain stored and reports still read legacy records.
