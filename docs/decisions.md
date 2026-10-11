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

## Follow-up improvements

- Review the real-data dashboard after import and splitting aggregate deposits.
- Automated quote adapters, with source approval and immutable valuation history.
- Versioned classification/ownership changes if historical reinterpretation is needed.
- More flexible imports and a full portable JSON export.

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
  Existing positions and legacy flow inputs remain stored and exported/backed up.

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
  Inputs accept ungrouped numbers or valid groups of three and reject malformed or
  foreign separator combinations. A single valid grouping separator is interpreted
  as grouping in that locale; use the locale decimal separator for fractions.
- Reuse Django locale formats and Intl.NumberFormat; no additional dependency.
  Stored cents, Decimal calculations, canonical exports, archived exact position
  values and the Overview importer's explicit Dutch source format stay independent
  of UI language. Whole-amount saves retain unchanged stored cents.
