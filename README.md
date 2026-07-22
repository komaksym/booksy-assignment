# Hardware Hub

A focused internal hardware-management tool built for Booksy's AI-Native Hardware
Hub assessment. This branch contains **Slice 1 only**: the runnable application shell,
bootstrap administrator, admin-created user accounts, signed-cookie login,
authorization, and the shared visual foundation.

The assignment calls for account creation by administrators, login restricted to
those accounts, a tested core, transparent trade-offs, and an AI development log.
Later reviewed slices add inventory, rental, and the AI-native auditor.

## Run locally

Prerequisites: Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
cp .env.example .env
# Replace every example credential and secret before running outside local development.
uv sync --locked
uv run uvicorn --app-dir src hardware_hub.app:app --reload
```

Open `http://127.0.0.1:8000/login`. The first startup creates the configured
bootstrap administrator only when no administrator exists.

## Validate

```bash
uv lock --check
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
uv build
```

The package build includes the Jinja templates and CSS required at runtime.

## Implementation status

### Fully implemented in Slice 1

- FastAPI/Jinja application shell and public health endpoint.
- Idempotent bootstrap administrator with Argon2 password hashing.
- Administrator-only creation and listing of active ordinary users.
- Login, an eight-hour inactivity timeout for the signed `user_id` session, and POST logout.
- Server-side role enforcement and responsive login/admin screens.
- Vertical authentication/authorization coverage plus a secret-safe startup regression test.
- Locked dependencies, package build configuration, and the minimal CI gate.

### Deliberate MVP shortcuts

- **Signed cookie instead of opaque server-side sessions.** It is tamper-evident and
  simple for the assessment, but not centrally revocable or encrypted. Authenticated
  responses refresh the cookie, so the eight-hour limit is an inactivity timeout,
  not an absolute maximum session lifetime. Production would use centrally managed
  sessions or company SSO.
- **`SameSite=Strict` plus POST-only mutations instead of synchronizer CSRF tokens.**
  This reduces risk but is not a complete CSRF defense. Production would add explicit
  CSRF protection.
- **Bootstrap credentials from environment variables.** This gives the private tool
  a first administrator without public registration. Production would provision
  access through identity infrastructure and secret rotation.

### Partial or missing by design

Inventory, dirty-seed handling, dashboard filtering/sorting, admin hardware
management, rental history, LLM auditing, and Railway deployment belong to later
review-gated slices. Slice 1 contains no fake dashboard or inactive navigation.

### Next three priorities

1. Import the supplied dirty seed losslessly and make its anomalies visible.
2. Add guarded inventory administration and the sortable/filterable dashboard.
3. Add owner-aware rent/return history, then the read-only deterministic/LLM audit.

## AI development

The prompt trail, data strategy, and correction log are recorded in
[`docs/ai-development-log.md`](docs/ai-development-log.md). The delivery plan is in
[`PLANS.md`](PLANS.md).
