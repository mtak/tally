# Production deployment

Deploy Tally on your existing Docker Compose server behind Traefik.
The application consists of one container and two persistent local volumes.
These instructions use Bash. Replace example hostnames, network and resolver names
with values from your existing infrastructure.

## 1. Prerequisites

- Docker Engine and the Docker Compose plugin on the server.
- Git access to the private repository https://github.com/OWNER/REPOSITORY.
- An existing Traefik instance and its external Docker network.
- DNS for your chosen hostname pointing to the server (or private routing/VPN).
- HTTPS certificates provided by Traefik and HTTP-to-HTTPS redirect configured there.
- Your existing access controls and encrypted off-host backup destination.

Tally does not deploy Traefik or provision DNS/certificates. Keep the database on
local disk; do not use NFS or object storage for the active SQLite file.
The current login has no built-in rate limiter: use private/VPN access or a suitable
Traefik middleware before exposing it to the internet.

## 2. Obtain and configure the application

On the production server, choose your usual applications directory:

    git clone git@github.com:OWNER/REPOSITORY.git
    cd tally
    cp .env.example .env
    chmod 600 .env

Do not overwrite an existing .env when updating an installation. Set:

| Variable | Value |
| --- | --- |
| DJANGO_SECRET_KEY | A unique, stable random secret |
| TALLY_HOST | Bare hostname, e.g. tally.example.com (no scheme/path) |
| TALLY_INSTANCE_NAME | Optional display name, e.g. Example portfolio; blank keeps the default appearance |
| TALLY_MONEY_PRECISION | `whole` (default) or `cents` for monetary display and input precision |
| TALLY_AUTH_ENABLED | `1` (default): require Django portfolio login; `0`: rely entirely on upstream authentication; other values fail startup |
| TALLY_IMPORT_HISTORY_ENABLED | `1` (default): enable historical CSV import; `0`: hide and disable the import page and management command; other values fail startup |
| TRAEFIK_NETWORK | Existing external Docker network, e.g. traefik |
| TRAEFIK_ENTRYPOINT | Existing HTTPS entrypoint, e.g. websecure |
| TALLY_TRAEFIK_ID | Router and service identifier, default `tally`; unique on the shared Traefik network |

`TALLY_TRAEFIK_ID` accepts 1–63 lowercase letters, digits, underscores or hyphens,
starting with a letter or digit. Invalid values fail application startup before
migrations. Compose project names isolate volumes; this identifier isolates routing.

Generate a secret locally with `openssl rand -hex 32`, then put it in .env.
Keep it stable between deployments; do not commit it or print a resolved Compose
configuration into logs. Compose reads .env automatically.

Confirm the external network exists:

    docker network inspect traefik

Replace `traefik` above with your configured network name. Production Compose sets
DEBUG=0, secure cookies, the allowed hostname and trusted HTTPS origin. It trusts
forwarded HTTPS headers from Traefik; do not expose the application port directly.

### Optional: certificate resolver and access middleware

If Traefik already supplies a default certificate/resolver for its HTTPS entrypoint,
no additional labels are necessary. Otherwise create `compose.prod.local.yaml`:

    services:
      app:
        labels:
          - "traefik.http.routers.${TALLY_TRAEFIK_ID:-tally}.tls.certresolver=letsencrypt"
          # Optional: existing middleware configured in your Traefik setup:
          # - "traefik.http.routers.${TALLY_TRAEFIK_ID:-tally}.middlewares=private-access@file"

Use your actual resolver/middleware names. This local override is ignored by Git.
Do not configure a new resolver here: it must already exist in Traefik.

### Optional: upstream authentication

Leave `TALLY_AUTH_ENABLED=1` unless an existing gateway authenticates every request.
With `0`, everyone reaching Tally can access and modify the entire shared portfolio,
including imports and exports. Tally neither validates identity/JWT headers nor
creates Django users from them. This setting alone provides no authentication.

Before setting `0`, secure the whole hostname and every path (including `/admin/`,
`/import/` and `/export/`). Block direct application access: keep host ports
unpublished, restrict container-network access to trusted infrastructure, and remove
alternate hostnames, routers and origin routes that bypass the gateway. Keep HTTPS,
allowed-host/origin settings, proxy header trust and CSRF protection in place.
`TALLY_TRUST_PROXY` only trusts the HTTPS scheme header; it does not authenticate users.

**Cloudflare Zero Trust:** configure a self-hosted Access application for the whole
hostname with an Allow policy restricted to your intended users. Avoid Bypass
policies. Protect the origin as well: use an existing Cloudflare Tunnel with Access
token validation, or enforce Access JWT validation at your trusted origin proxy.
Prevent direct public origin access, including access through Traefik that skips
Access. Cloudflare's [self-hosted application guide](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)
describes application policies and origin token validation. Tally provisions none
of these services.

**Traefik authentication:** attach your existing authentication middleware to the
entire configured router in `compose.prod.local.yaml`, using your actual middleware name:

    services:
      app:
        labels:
          - "traefik.http.routers.${TALLY_TRAEFIK_ID:-tally}.middlewares=existing-auth@file"

For delegated authentication, [Traefik ForwardAuth](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/forwardauth/)
only forwards requests when the authentication service permits them. Check that
the middleware is attached to every route to Tally, denies unauthenticated traffic
and fails closed when its authentication service is unavailable. Configure the
service in your existing infrastructure; this repository does not provision it.

Verify these boundaries with application authentication still enabled, then set
`TALLY_AUTH_ENABLED=0` in `.env` and recreate the app with `dc up -d` (using the
function defined below). A restart alone does not reload environment variables.
In a fresh browser session, verify gateway denial before sign-in and portfolio
access after sign-in, including a form save, import and export. Verify direct
origin/bypass routes are unreachable. Invalid/missing CSRF tokens must still fail.

Portfolio login redirects to `/`; the portfolio sign-out control is hidden.
POST `/logout/` redirects to `/` without ending Django or upstream sessions;
GET `/logout/` returns 405. Use your gateway's own sign-out to end upstream access.
`/admin/` retains separate Django staff authentication and permissions; use
`/admin/login/` and the admin's own logout. Create a superuser only if you need admin
access. Disabling portfolio login never grants staff or superuser status.
To restore portfolio login, set `TALLY_AUTH_ENABLED=1` and recreate the app.

## 3. Define the production command

Run this in the repository directory in each new Bash session. It automatically
includes the optional local override:

    tally_compose_files=(-f compose.yaml -f compose.prod.yaml)
    if [ -f compose.prod.local.yaml ]; then
      tally_compose_files+=(-f compose.prod.local.yaml)
    fi
    dc() {
      local tally_revision
      tally_revision="$(git rev-parse HEAD)" || return
      TALLY_GIT_COMMIT="$tally_revision" docker compose -p tally-prod "${tally_compose_files[@]}" "$@"
    }

Use this `dc` function for all commands below. Do not include compose.dev.yaml in
production. Keep the project name tally-prod stable: changing it selects different
volumes. The default volumes are tally-prod_tally-data and tally-prod_tally-backups.

Validate without printing secrets, then start:

    dc config --quiet
    dc up --build -d
    dc ps
    dc logs --tail=100 app

Startup runs Django migrations, then Gunicorn on internal port 8000. The process runs
as UID/GID 10001, with one worker and four threads. No production host port is published.
WhiteNoise serves bundled static assets; no external CDN or separate webserver is needed.

The `dc` function supplies the current checkout's commit as a build argument. The
image retains it as `TALLY_GIT_COMMIT` and the OCI revision label. The bottom-left
version shows its first seven characters; hover for the full SHA. On mobile the
same release label appears in the page footer. Reusing or rolling back an image
retains that image's revision. Build from a clean checkout to identify a release
accurately; do not override `TALLY_GIT_COMMIT` in the container's runtime environment.

## 4. Create your login and check HTTPS

After migrations finish and Gunicorn is listening:

With the default `TALLY_AUTH_ENABLED=1`, create a Django login below. With `0`,
check gateway authentication at `/` instead; creating a user is optional for admin
access, and `/login/` redirects to `/` rather than displaying a login form.

    dc exec app python manage.py createsuperuser

Enter your own username/password interactively. There is no default production account
and no self-service registration. Do not seed demo data in the production portfolio.

Open https://tally.example.com/login/ using your actual hostname. Verify the certificate,
sign-in, language switching, and that CSS/charts load. A basic HTTP check is:

    curl --fail --silent --show-error --output /dev/null --write-out '%{http_code}\n' https://tally.example.com/login/

Expect HTTP 200 (or your configured access-gateway flow if a middleware protects it).
Check that the application container has no publicly mapped port in `dc ps`.

## 5. Import your history

From the authenticated Import history page:

1. Select your Google Sheets Overview CSV with confirmation unchecked for a preview.
2. Review dates and warnings.
3. Select the file again, check confirmation, and import.
4. Review the latest total, source reconciliation, account owners, liquidity and dates.

Existing dates are not overwritten. Do not mix demo data with the production import.
The importer creates the new joint account without a historical balance; enter full
joint balances and Tally applies 50%. Split aggregate Example Deposit Provider into separate deposit
accounts by closing the aggregate on the first detailed date to avoid double counting.
The confirmed malformed date header maps to 1 August 2026. Whole-euro source rounding
can cause small differences with source totals.

## 6. Backups

Use the online backup command, which makes a consistent SQLite backup while the
application is running. Do not copy a live database file directly.

    tally_backup_name="tally-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
    dc exec -T app python manage.py backup "/backups/$tally_backup_name"
    mkdir -p backups
    chmod 700 backups
    dc cp "app:/backups/$tally_backup_name" "backups/$tally_backup_name"
    chmod 600 "backups/$tally_backup_name"

The backup command creates an exclusive private temporary file (mode 600) before
copying with the online API. It closes both connections, then publishes the completed
backup atomically without replacing any existing path, including symlinks. Failures
remove the temporary file; an interrupted/killed process may leave a private
`.tally-backup-*` file that can be removed after confirming no backup is running.
The destination directory must support hard links (the supplied local volume does).
Backups contain financial data and Django user/password-hash/session data.
Move a copy to your existing encrypted
off-host backup process and retain .env separately in your secret store.
Both Compose volumes are on this server: the /backups volume alone is not off-host
protection. No R2 or other cloud storage is configured.

Schedule this workflow using your existing infrastructure. Test restores periodically.
CSV export is not a full backup: it omits positions, settings and login data.

## 7. Updates

Take and copy out a backup first. Save the deployed revision and image so a rollback
does not depend on downloading old dependencies:

    git rev-parse HEAD > backups/pre-update-revision.txt
    tally_previous_image="$(dc images -q app | head -n 1)"
    docker image tag "$tally_previous_image" tally:pre-update

Keep normal Git cleanliness checks and review the update before deploying:

    git status --short
    git pull --ff-only
    dc config --quiet
    dc build
    dc up -d
    dc logs --tail=100 app

Migrations run automatically on startup. Verify login, latest valuation, and key totals.
Persisted volumes survive container replacement. Do not use `docker compose down -v`
or prune these volumes: that deletes database/backups.

## 8. Restore and rollback

Restore into an isolated instance first whenever possible. Never run old application
code against an upgraded schema without establishing migration compatibility.
For an incompatible rollback, restore the pre-update database and corresponding code/image
together. Stop all application writers before replacing SQLite files.

### Test a backup without touching production

Use the retained/current image and a fresh volume, choosing an unused volume name:

    docker volume create tally-restore-check
    tally_restore_image="$(dc images -q app | head -n 1)"
    docker run --rm --user 0:0 \
      -v tally-restore-check:/restore \
      -v "$PWD/backups:/source:ro" \
      --entrypoint sh "$tally_restore_image" \
      -c 'cp "/source/$1" /restore/tally.sqlite3 && chown 10001:10001 /restore/tally.sqlite3' sh "$tally_backup_name"

Check integrity and the number of historical observations without publishing a port:

    docker run --rm -v tally-restore-check:/restore \
      --entrypoint python "$tally_restore_image" -c \
      'import sqlite3; c=sqlite3.connect("file:/restore/tally.sqlite3?mode=ro", uri=True); print(c.execute("PRAGMA integrity_check").fetchone()[0]); print("Observations:", c.execute("SELECT COUNT(*) FROM wealth_valuation").fetchone()[0])'

Expect `ok` and the expected observation count. This verifies the database copy;
also check the restored application's latest dates/totals in an isolated test deployment
before relying on a new backup strategy. The test volume remains available for inspection.

### Replace the production database

Select the verified backup filename (set tally_backup_name if this is a new shell).
Take another backup of the current database before replacing it.
Then:

    dc stop app
    dc run --rm --no-deps --user 0:0 \
      -v "$PWD/backups:/restore:ro" \
      --entrypoint sh app -c \
      'test -f "/restore/$1" && cp "/restore/$1" /data/tally.restore.sqlite3 && chown 10001:10001 /data/tally.restore.sqlite3 && chmod 600 /data/tally.restore.sqlite3 && rm -f /data/tally.sqlite3-wal /data/tally.sqlite3-shm /data/tally.sqlite3-journal && mv /data/tally.restore.sqlite3 /data/tally.sqlite3' sh "$tally_backup_name"

The command bypasses normal startup/migrations and replaces the stopped database.
For an ordinary restore to the current application:

    dc up -d
    dc logs --tail=100 app

For rollback to the saved pre-update image, restore its matching backup first.
Check out the saved revision after preserving any working changes, and add a temporary
image override:

    git checkout --detach "$(cat backups/pre-update-revision.txt)"
    printf 'services:\n  app:\n    image: tally:pre-update\n' > /tmp/tally-rollback.yaml
    dc -f /tmp/tally-rollback.yaml up -d --no-build --pull never

Verify the actual running image and latest data. Preserve the rollback override and
reconcile the deployed Git revision before future upgrades; do not blindly rebuild
or pull while investigating a rollback.

## Separate portfolio / second instance

Use a distinct Compose project, hostname, secret and `TALLY_TRAEFIK_ID` for each
portfolio, for example `tally-example-a` and `tally-example-b`. Each project gets independent
data/backup volumes; each routing identifier gets independent Traefik router/service
labels with explicit linkage to internal port 8000. They may share the existing
Traefik network. Choose separate session/CSRF cookie names when sharing a browser
hostname in development.

Existing deployments keep identifier `tally` by default, so no routing migration is
required. To rename it, set `TALLY_TRAEFIK_ID` and update any local middleware or
certificate labels to the list syntax above; remove old hardcoded router labels,
then validate with `dc config --quiet` and recreate the app in your normal deployment
cycle. Keep the existing Compose project name to preserve volume selection. A new
identifier does not require a new database or volume.

Give each instance a distinct `TALLY_INSTANCE_NAME` in its own environment file,
for example `"Example portfolio"` and `"Second example portfolio"`. The name appears in the
shared header, including before login, and in browser tab titles. It is a display
label; it does not change portfolio access or data isolation. Avoid sensitive names
if the login page is publicly accessible. Omitted or whitespace-only names preserve
the default Tally appearance.

Compose passes this setting to both development and production containers. After
changing it, recreate the app with `dc up -d` (a restart alone does not reload the
container environment). For development, use the usual Compose files and the
instance's `--env-file` and project name with `up -d`. Without Docker, export
`TALLY_INSTANCE_NAME` before starting Django and restart the process after changes.

## Troubleshooting

- **404 from Traefik:** inspect hostname, entrypoint, router labels and shared network.
- **502 from Traefik:** check migrations/Gunicorn logs, network selection and internal port 8000.
- **CSRF/login errors:** use HTTPS; confirm TALLY_HOST matches the browser hostname,
  proxy headers and generated CSRF_TRUSTED_ORIGINS. Do not disable CSRF to fix routing.
- **Permission denied:** inspect ownership on /data and /backups; the app UID/GID is 10001.
- **Database locked:** keep SQLite on local disk, use the supplied worker setup, and
  investigate concurrent imports/writers before increasing worker count.
- **Changed totals after import:** review source rounding, closed/aggregate accounts and
  preserved historical tax adjustments. Do not replace missing values with zero.

Production Compose has been configuration-validated and the image tested locally.
The actual server hostname, resolver and middleware remain deployment-specific.
