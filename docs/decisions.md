# Product and architecture decisions

- One self-hosted portfolio per instance. Dutch and English, EUR reporting.
- English and dark mode are the first-visit defaults, independent of browser language
  and OS color preference. Explicit language cookies and saved theme choices take
  precedence. Initialize the theme before rendering; unavailable storage falls back
  to dark mode. Dutch and light mode remain available in the existing controls.
- Owner types: private, sole proprietor and company; holding/subsidiary metadata.
  Underlying assets are counted once. A shared private bank account counts at 50%.
- Any valuation date, draft/resume workflow, explicit observation dates, blanks not zeros.
- Whole-account returns from balance and total deposits/withdrawals. Midpoint estimate
  for period percentages. No inferred individual trades or time-weighted returns.
- Positions classify assets; account value remains the authoritative wealth amount.
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
- Dated major cash flows for a more accurate Modified Dietz estimate.
- Copy forward a prior holdings list as an explicitly dated draft for review.
- Automated quote adapters, with source approval and immutable valuation history.
- Versioned classification/ownership changes if historical reinterpretation is needed.
- More flexible imports and a full portable JSON export.

## Investment flow entry (#3)

- Both period totals and cumulative deposit/withdrawal counters are supported.
- Period totals store explicit opening and closing valuation dates. Backdated
  observations do not reinterpret recorded totals; the opening date can be changed
  explicitly after reviewing the amounts.
- The user confirmed cumulative totals cover all deposits and withdrawals since
  account opening, with a zero opening balance. Total euro result is therefore
  current value minus cumulative deposits plus cumulative withdrawals, available
  on the first reading. No lifetime or annualized percentage is inferred.
- A comparison baseline is only needed for period results. Later observations
  compare counters within the same baseline. A decrease requires correcting the
  entry or explicitly starting a new comparison, with no period return across that
  reset. Totals must still cover the complete account history; truncated counters
  are not supported. Missing or incompatible endpoints produce no period return.
- Switching modes retains the inactive inputs and their opening dates; only the
  selected mode participates in calculations. The CSV export includes both input
  sets, mode and endpoint/baseline dates.
- Confirmed zero flows use a dedicated shortcut. Blank flows remain unknown.
- Tax basis remains independent of performance counters and imported adjustments.
