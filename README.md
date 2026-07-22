# Hardware Hub

A focused internal hardware-management tool built for Booksy's AI-Native Hardware
Hub assessment. This branch contains **Slices 1 and 2**: authenticated access plus a
server-rendered inventory that preserves malformed source data, derives objective
findings, and lets administrators correct canonical values without rewriting the
original evidence.

The assignment calls for account creation by administrators, login restricted to
those accounts, a tested core, transparent trade-offs, and an AI development log.
Later reviewed slices add rental and the AI-native auditor.

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

The package build includes the Jinja templates, CSS, and exact JSON seed required at
runtime.

## Implementation status

### Fully implemented through Slice 2

- FastAPI/Jinja application shell and public health endpoint.
- Idempotent bootstrap administrator with Argon2 password hashing.
- Administrator-only creation and listing of active ordinary users.
- Login, an eight-hour absolute maximum for the signed `user_id` session, and POST logout.
- Server-side role enforcement and responsive login/admin screens.
- Vertical authentication/authorization coverage plus a secret-safe startup regression test.
- Locked dependencies, package build configuration, and the minimal CI gate.
- Lossless, idempotent import of all 11 source records under generated internal UUIDs.
- Immutable raw payloads beside editable canonical brand, date, status, notes, and history.
- Eight pure deterministic rules producing the exact 11 initial finding occurrences.
- Authenticated inventory filtering and stable sorting with visible validation errors.
- Administrator create, edit, hard-delete, mark-repair, and clear-repair operations.
- Side-by-side source/canonical correction with legacy assignee redaction.
- Ordinary-user views that omit canonical-null rows, findings, provenance, and admin controls.
- Responsive sidebar/top navigation and table-scoped narrow-screen overflow.

### Deliberate MVP shortcuts

- **Signed cookie instead of opaque server-side sessions.** It is tamper-evident and
  simple for the assessment, but not centrally revocable or encrypted. Under the
  generated lockfile, read-only authenticated activity does not refresh the cookie,
  so the eight-hour value is an absolute maximum lifetime rather than an inactivity
  timeout. Production would use centrally managed sessions or company SSO.
- **`SameSite=Strict` plus POST-only mutations instead of synchronizer CSRF tokens.**
  This reduces risk but is not a complete CSRF defense. Production would add explicit
  CSRF protection.
- **Bootstrap credentials from environment variables.** This gives the private tool
  a first administrator without public registration. Production would provision
  access through identity infrastructure and secret rotation.
- **Persistent initialization marker instead of migrations.** A marker prevents
  duplicate imports and prevents deleted rows from reappearing after restart. Production
  schema evolution would use an explicit migration system.
- **Single-process TinyDB mutations.** Each route re-reads current state before one
  write, but there is no transaction or multi-worker guarantee. A production service
  would use a transactional database.
- **Permanent hard deletion without a deletion log.** This directly satisfies the
  assignment but provides no recovery or audit trail.
- **Derived findings instead of stored resolution state.** Findings always reflect
  current canonical data plus immutable source evidence.

### Partial or missing by design

Rent/return ownership, rental history, LLM auditing, and Railway deployment belong to
later review-gated slices. Slice 2 intentionally contains no rental controls, audit
page, fake metrics, pagination, JavaScript dependency, or inactive future navigation.

### Next three priorities

1. Add owner-aware rent/return history with deterministic safety gates.
2. Add the read-only deterministic/LLM audit with provider-failure fallback.
3. Document and validate Railway-ready single-worker deployment configuration.

## AI development

The prompt trail, data strategy, and correction log are recorded in
[`docs/ai-development-log.md`](docs/ai-development-log.md). The delivery plan is in
[`PLANS.md`](PLANS.md).
