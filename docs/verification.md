# First-release verification

Automated checks cover ownership rounding, missing versus zero values, carry-forward
dates, future/closed account handling, mortgage/pension filters, gross allocations,
tax corrections including losses, historical overrides, account returns, unknown flows,
CSV duplicate/conflict handling, authentication, NL/EN page rendering, localized input,
draft/publish persistence and movement reconciliation.

Manual browser checks use fictional demo data: sign-in, language switching, home filter
with chart/total updates, the performance waterfall, and saving a partially completed
valuation. Screenshots use fictional data only.

Fictional Overview fixtures were imported into a disposable local database, with source totals reconciling within the documented whole-euro rounding tolerance.
The online SQLite backup passed integrity and restored row-count checks. Temporary
verification data was deleted and is never committed.

Docker image build and development startup are checked locally. Production Compose
configuration is validated, but deployment to the actual Traefik server requires the
operator's hostname/network/certificate configuration and has not been performed.

Issue #45 verification uses fictional claims: same-quarter EUR 10,000 + EUR 15,000,
ownership rounding, business separation, due-on-valuation and overdue dates, missing
maturities/balances, nonpositive balances, published carry-forward, start/closure dates
and replacement aggregates. Read-only localized view tests protect stored observations,
interest and tax adjustments and unchanged report output. Browser checks cover English
and Dutch, whole amounts/cents, valuation selection, both charts, dark/light themes,
and a 390px mobile viewport with keyboard-scrollable tables and no page overflow.


## Backup and production reliability (#32, #37, #39)

CI builds one image and runs `python tests/production_smoke.py tally:test`.
The smoke check renders two production configurations with fictional hosts/secrets,
checks disjoint router/service labels and independent volumes, and rejects invalid
routing identifiers. It starts the image's default migration/Gunicorn command as
UID/GID 10001 with DEBUG off, verifies proxy HTTPS trust, secure cookies, authenticated
HTTP dashboard access and bundled static assets, and confirms no dev login is created.

The same image and fictional demo database exercise online backup, mode 600,
no-overwrite, integrity and SQL-content comparison. A second fresh data volume
receives the backup, then starts the same image and verifies restored portfolio
and login data through authenticated HTTP. No host ports or Traefik network are
needed. Cleanup targets only UUID-named containers and volumes created by this run.
Run it locally after building an image; production deployment is a separate action.

`tests/test_backup.py` additionally checks permissions before destination connection
under umask 022, existing files/directories/symlinks (including dangling ones),
concurrent creation, partial-copy/publication failures, explicit connection closure,
missing sources and restored fictional SQLite content. No portfolio volumes are used.

## Shared Overview preflight (#26, #27)

Fictional regressions cover missing/renamed account rows, empty dates, source totals,
EUR 2 tolerance, optional rows and historical blanks, explicit zero, metadata conflicts,
start/closure boundaries, safe customization preservation, owner parents, duplicate
files/dates, apply-time rechecking and rollback after a late write failure. Web preview,
confirmed import and CLI preview share the same compatibility result.

Playwright MCP against a disposable local database checked blocked unrecognized
files, English/Dutch row inventories and exact reconciliation, confirmed header
correction, a successful confirmed import and a rejected reused-account pension
conflict. The preview stayed within the viewport at 390px. No real portfolio was
used for these checks. Required Python checks and JavaScript regressions passed;
release CI also exercises the Docker production startup/backup/restore smoke check.

## Financial validation (#28, #29)

Fictional focused regressions cover strict Dutch monetary syntax, nonfinite values,
signed 64-bit edges/overflow, positive and negative half-cent ties, pre-rounding
sign rejection and translated row/date errors. Ordinary/admin/model writes share
ownership, date, balance and rate checks. Tests exercise atomic queryset/bulk and
late import rejection, persisted partial updates, related metadata changes, signed
credit-card debt/credit and optional amounts. Raw-SQL checks verify local database
constraints independently; the migration compatibility audit rejects explicit
legacy sign violations without modifying their records. Reporting still reads a
constructed legacy negative claim. No real financial fixtures are committed.
