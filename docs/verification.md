# First-release verification

Automated checks cover ownership rounding, missing versus zero values, carry-forward
dates, future/closed account handling, mortgage/pension filters, gross allocations,
tax corrections including losses, historical overrides, account returns, unknown flows,
CSV duplicate/conflict handling, authentication, NL/EN page rendering, localized input,
draft/publish persistence and movement reconciliation.

Manual browser checks use fictional demo data: sign-in, language switching, home filter
with chart/total updates, the performance waterfall, and saving a partially completed
valuation. No real-data screenshots are used.

Fictional example data was imported into a disposable local database: 12 dates and
123 observations, with totals reconciling to within EUR 2 (whole-euro source rounding).
The online SQLite backup passed integrity and restored row-count checks. Temporary
verification data was deleted and is never committed.

Docker image build and development startup are checked locally. Production Compose
configuration is validated, but deployment to the actual Traefik server requires the
user's hostname/network/certificate configuration and has not been performed.

Issue #45 verification uses fictional claims: same-quarter EUR 10,000 + EUR 15,000,
ownership rounding, business separation, due-on-valuation and overdue dates, missing
maturities/balances, nonpositive balances, published carry-forward, start/closure dates
and replacement aggregates. Read-only localized view tests protect stored observations,
interest and tax adjustments and unchanged report output. Browser checks cover English
and Dutch, whole amounts/cents, valuation selection, both charts, dark/light themes,
and a 390px mobile viewport with keyboard-scrollable tables and no page overflow.
