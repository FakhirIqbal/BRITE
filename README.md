# BRITE ABA Intake & Operations System — Backend

Django 6 + Django REST Framework on Neon PostgreSQL. This repository holds the
API for the Intake & Operations System. Milestone 2 (System Foundation, Login &
Security) is implemented here.

## What Milestone 2 delivers

| Area | Where |
| --- | --- |
| Google Workspace single sign-on, Workspace group → role mapping, Directory sync | `apps/accounts` (`google.py`, `services.py`, `auth_views.py`) |
| Capability groups, role defaults, individual exceptions, temporary grants, System Owners | `apps/accounts` (`roles.py`, `access.py`, `admin_views.py`) |
| Access enforced in the API (DRF permissions) **and** in the database (Postgres row-level security) | `apps/accounts/permissions.py`, `apps/core/db.py`, each app's `0002_*` migration |
| Core schema: Client, Service Episode, six workstreams, permanent Client ID + Code Name | `apps/clients` |
| Concurrent-write protection (versioned saves refused with who/when) | `apps/core/services.py`, `apps/core/exceptions.py` |
| Append-only audit foundation (field, old/new value, actor, actor type, hash chain, DB trigger) | `apps/audit` |
| First configuration screens: status sets | `apps/configuration` |
| Shared Drive connection: base folders permissioned by Workspace group | `apps/drive` |

## Setup

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env            # fill in SECRET_KEY, DATABASE_URL (Neon) and the Google values
venv/bin/python manage.py migrate
venv/bin/python manage.py seed_foundation            # role defaults, group mapping, status sets, System Owners
venv/bin/python manage.py seed_foundation --dev-users  # plus fictional accounts for the development sign-in
venv/bin/python manage.py runserver 8000 --nothreading
```

`--nothreading` matters when the database is far away (each new thread would open a new TLS
connection to Neon); in production run gunicorn with a fixed worker/thread pool in the same region.

### Environment variables

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` | Django basics |
| `DATABASE_URL` | Neon PostgreSQL connection string (`sslmode=require`) |
| `TEST_DATABASE_URL` | Optional local Postgres for `manage.py test` (role must be NOSUPERUSER so RLS applies) |
| `FRONTEND_ORIGINS` | Origins allowed to call the API with cookies (CORS + CSRF trusted) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_WORKSPACE_DOMAIN` | Workspace SSO (Google Identity Services ID tokens, hosted-domain checked) |
| `GOOGLE_SERVICE_ACCOUNT_FILE`, `GOOGLE_DIRECTORY_ADMIN_EMAIL` | Directory API (group membership sync at sign-in; domain-wide delegation) |
| `GOOGLE_SHARED_DRIVE_ID` | Shared Drive that holds the Potential Clients / Clients / Staff folders |
| `BRITE_SYSTEM_OWNER_EMAILS` | The two named BRITE administrators seeded as System Owners |
| `DEV_AUTH_ENABLED` | Development-only sign-in with seeded fictional accounts (ignored unless `DEBUG=True`) |

Without the Google service account, administrators record Workspace group membership on each
user's Roles panel; the application behaves identically once Directory sync is configured.

## Access model in one paragraph

A user holds every role whose mapped Workspace group they belong to. Each role has a default
level (None / View / Edit) per capability group; the highest level across roles wins, then
individual exceptions apply (a removal outlasts later group changes; temporary grants expire via
`manage.py expire_temporary_grants`, audited as a *scheduled* actor). DRF permission classes check
the resulting capabilities, and the same capability set is placed in the transaction with
`set_config('app.*')` so Postgres row-level-security policies (FORCE RLS, fail closed) check it
again on every query. System Owner is system access, not content access; at least two exist.

## Write path

All editable records extend `VersionedModel`. Writes go through
`apps.core.services.save_versioned`, which performs `UPDATE … WHERE version = expected`; a stale
version raises HTTP 409 `concurrent_write` naming who changed the record and when. Every applied
change writes an `AuditEvent` (field, old value, new value, actor, actor type, origin event, hash
chain). The audit table refuses UPDATE/DELETE by trigger and has no policy allowing them.

## Tests

```bash
venv/bin/python manage.py test
```

28 tests cover the Milestone 2 acceptance criteria: role-scoped sections, restricted routes and
database-level denial, one open episode per client, closed episodes read-only (API and database),
concurrent-save refusal, audit history with actor/actor type, append-only enforcement, hash-chain
integrity, exceptions/System Owner rules and status configuration.

## Scheduled jobs

- `manage.py expire_temporary_grants` — nightly; removes expired temporary grants.
