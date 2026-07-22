# Hardware Hub

Hardware Hub is a focused internal hardware-management product for Booksy's
AI-Native recruitment assessment. It preserves the supplied malformed inventory as
immutable evidence, derives trusted canonical fields for operations, blocks
objectively unsafe rentals, and gives administrators a read-only deterministic and
optional DeepSeek audit.

The project deliberately favors a complete, reviewable vertical journey over
production infrastructure. FastAPI renders Jinja pages, TinyDB stores one JSON file,
and deterministic rules remain authoritative even when the model is missing, fails,
or returns invalid output.

## Prerequisites

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)

## Local setup

```bash
cp .env.example .env
# Replace every example credential and secret.
uv sync --locked
uv run uvicorn --app-dir src hardware_hub.app:app --reload
```

Open `http://127.0.0.1:8000/login`. On the first startup, the application creates the
bootstrap administrator only when no administrator already exists and imports the
11-record seed only when the persistent initialization marker is absent.

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | yes | `development`, `test`, or `production`; production enables the Secure session-cookie flag. |
| `TINYDB_PATH` | yes | JSON database path. Use `/data/hardware-hub.json` on the Railway volume. |
| `SESSION_SECRET` | yes | At least 16 characters; use a long random secret outside local development. |
| `BOOTSTRAP_ADMIN_EMAIL` | yes | Email for the first idempotently created administrator. |
| `BOOTSTRAP_ADMIN_PASSWORD` | yes | Initial administrator password. |
| `LLM_BASE_URL` | optional | OpenAI-compatible DeepSeek base URL, for example `https://api.deepseek.com`. |
| `LLM_MODEL` | optional | Configurable model; the example configuration uses `deepseek-v4-flash`. |
| `LLM_API_KEY` | optional | DeepSeek bearer token. Keep it out of source control and browser output. |

All three LLM variables must be non-blank before the browser action is enabled.
Without them, deterministic auditing remains fully available and a forged direct POST
returns a safe warning without making a network request.

## Validation

```bash
uv lock --check
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
uv build
```

The committed implementation is created only after the test-first audit scenario,
full pytest suite, Ruff checks, lockfile check, package build, and diff check pass in
the one-time branch workflow. Pull-request CI repeats the repository's minimal gate.
The package includes the Jinja templates, CSS, and exact JSON seed required at runtime.

## Manual product journey

1. Log in with the bootstrap administrator and create an ordinary user under **Users**.
2. Inspect the inventory as the administrator. Confirm all 11 source records survive,
   both source-ID `4` rows have distinct internal identities, source `10` exposes its
   malformed original values beside unset canonical values, and the legacy assignee
   is shown only as present and redacted.
3. Correct source `10` with a canonical brand, purchase date, and status. Its three
   repairable findings clear while the immutable raw payload remains unchanged.
4. Log in as the ordinary user. Rent a safe available item, verify another user cannot
   return it, then return it as the owner and inspect the append-only history.
5. Log back in as administrator and open **Audit**. Review the deterministic table.
   Configure the optional LLM variables to request a separate DeepSeek second opinion.

## Implemented behavior by slice

### Slice 1 — shell and access

- Public `/health` endpoint and FastAPI/Jinja application shell.
- Idempotent bootstrap administrator, Argon2 password hashing, and administrator-created
  ordinary users; there is no public registration.
- Signed session cookie containing only `user_id`, with an eight-hour absolute maximum,
  `HttpOnly`, `SameSite=Strict`, and `Secure` in production.
- Active-user reload and server-side role enforcement on every request.

### Slice 2 — dirty inventory

- Lossless, idempotent import of every supplied object under a generated internal UUID.
- Immutable `raw_payload` beside editable canonical fields.
- Eight deterministic rule codes and the exact 11 initial finding occurrences.
- Server-side filtering/sorting, administrator CRUD and repair transitions, canonical
  correction, ordinary-user concealment of canonical-null rows, and legacy email
  redaction at render time.

### Slice 3 — guarded circulation

- Ordinary-user-only rent and owner-only return POST routes.
- Fresh state checks for canonical availability, null holder, and deterministic critical
  findings; warnings do not block rental and returns are not finding-gated.
- One coherent TinyDB update per accepted transition and zero writes on rejection.
- Append-only rental/release history with role-safe actor labels.
- A bounded administrator edit override can release an application-held item to
  `Available` or `Repair` with attributable history.

### Slice 4 — audit and release handoff

- Administrator-only `GET /admin/audit` and `POST /admin/audit/llm` routes.
- Fresh deterministic findings rendered in a stable global table with hardware links.
- One allowlisted snapshot containing every current hardware document, including
  canonical-null records, but excluding raw payloads, source IDs, users, emails,
  passwords, sessions, secrets, holders, rental history, and timestamps.
- One direct ten-second HTTPX chat-completions call with JSON output, thinking disabled,
  strict Pydantic schemas, atomic rejection, submitted-ID validation, and no retries.
- Provider/configuration/JSON/schema/unknown-ID failures preserve the complete
  deterministic result and leave inventory byte-for-byte equivalent at the document
  level.
- AI suggestions render separately and never mutate or govern operational state.
- One-worker Railway configuration and a documented `/data` persistence contract.

## Data strategy

The malformed fixture is product input, not setup noise. Each source object is retained
as a JSON value-equivalent deep copy in `raw_payload`; key order and whitespace are not
meaningful, but values are never silently corrected. The supplied ID is provenance only
and is never used as application identity, update key, or deduplication key.

Canonical fields are the editable operational view. Unsupported dates/statuses become
canonical nulls while the original value remains visible to administrators. Findings
are derived on every request by `find_issues`; they are not stored or acknowledged.
This makes corrections observable without erasing evidence.

The model snapshot is a separate explicit projection. It includes canonical fields,
editable notes/history, a boolean indicating legacy-assignee presence, and only the
code/severity of deterministic findings. Notes/history are intentionally included
because interpreting them is the feature.

## Security, privacy, and authority boundaries

- The signed cookie is tamper-evident, not encrypted or centrally revocable.
- `SameSite=Strict` and POST-only mutations reduce cross-site request risk but are not a
  complete CSRF defense.
- The source `assignedTo` email is never rendered or sent to the model.
- Free-text notes/history may still contain personal data or instruction-like content.
  The prompt labels all snapshot content untrusted, the model has no tools or write path,
  and output is schema-validated, but hardened redaction and prompt-injection defenses
  are outside this MVP.
- Deterministic findings alone control rental safety. Model severity is presentation
  metadata only: an AI `critical` suggestion cannot block a rental, and an omitted
  deterministic critical finding cannot unblock one.
- Provider bodies, stack traces, raw exceptions, credentials, request snapshots, and
  free-text content are not shown in browser warnings or intentionally logged.

## Deliberate shortcuts and why

- **Signed cookie instead of persisted sessions or SSO:** small and sufficient for the
  assessment; production needs central revocation and identity integration.
- **No synchronizer CSRF tokens:** strict same-site cookies plus POST-only mutations keep
  the implementation bounded; production needs complete CSRF protection.
- **TinyDB with one worker/replica:** keeps the full project understandable; it does not
  provide transactional multi-process writes. Production should use a relational DB.
- **Persistent initialization marker instead of migrations:** prevents duplicate import
  and deleted-row resurrection; production needs schema migrations.
- **Permanent hard deletion:** directly satisfies the assignment but has no recovery or
  deletion audit trail.
- **One LLM schema and provider call:** enough to demonstrate safe optional AI value;
  there are no retries, streaming, background jobs, model adapters, or stored runs.
- **Manual browser/release verification instead of automated E2E/deployment tests:** the
  repository stays focused on five high-value integration behaviors.
- **No automated backups or runtime `/data` guard:** Railway storage correctness depends
  on the documented volume configuration and operator checks.

## Partial or missing work

- Public registration, invitations, password reset/change, session revocation UI, and SSO.
- Pagination, notifications, due dates, reassignment, rental limits, and user-facing audit.
- Finding acknowledgement/history, automatic repair, AI writes, tools, agents, RAG, and
  persisted audit runs.
- Transactional concurrency, multiple workers/replicas, backup automation, and migrations.
- Hardened free-text redaction, moderation, prompt-injection detection, byte limits, and
  a general LLM gateway.
- Automated browser, load, deployment, and redeploy-persistence tests.

## Top three improvements with another 24 hours

1. Replace TinyDB with PostgreSQL transactions and explicit migrations, preserving the
   raw/canonical model and transition invariants.
2. Add centrally revocable company authentication plus full CSRF protection and an
   administrator deletion/audit trail.
3. Add a hardened LLM privacy boundary with redaction, request/response size limits,
   structured observability, and automated browser/deployment smoke coverage.

## AI development disclosure

ChatGPT/Codex assisted with repository exploration, design criticism, implementation,
test generation, review, and documentation. Every accepted change was constrained by
the checked-in specifications, inspected as a diff, and required deterministic tests
and CI before being presented as complete.

Representative prompt trail:

1. Preserve every malformed source object while defining separate canonical fields and
   deterministic findings; do not silently repair or key by source ID.
2. Implement ordinary-user rent/owner-return transitions with fresh reads, one coherent
   update, no-write rejection, and privacy-aware history.
3. Review the rental PR independently, treat review questions as possible real defects,
   and patch held-item recovery, return-after-new-safety-evidence, role-scoped filters,
   and oversized tests.
4. Implement the approved Slice 4 specification test-first: a read-only deterministic
   audit plus an optional allowlisted DeepSeek second opinion with strict atomic fallback.

Corrections made after review include the bounded administrator held-item release, the
safety-handoff regression, ordinary-user concealment of the correction-only status
filter, splitting the rental acceptance test into focused journeys, and making every
invalid model response discard all AI rows rather than presenting partial output.
The longer development log is retained in [`docs/ai-development-log.md`](docs/ai-development-log.md).

## Railway deployment

`railway.toml` defines one Railpack service with this start command:

```text
uv run uvicorn --app-dir src hardware_hub.app:app --host 0.0.0.0 --port $PORT --workers 1
```

Configure Railway with:

- one service, one replica;
- a persistent volume mounted at `/data`;
- `TINYDB_PATH=/data/hardware-hub.json`;
- `ENVIRONMENT=production`;
- sealed `SESSION_SECRET`, `BOOTSTRAP_ADMIN_EMAIL`, and
  `BOOTSTRAP_ADMIN_PASSWORD` values;
- optional sealed `LLM_API_KEY`, plus `LLM_BASE_URL=https://api.deepseek.com` and
  `LLM_MODEL=deepseek-v4-flash`; and
- `/health` as the health-check path.

After publication, verify `/health`, bootstrap login, user creation, all 11 dirty rows,
source `10` correction, one safe rent/return, the deterministic audit, one real DeepSeek
request when a funded key is supplied, and persistence of a known data change across one
redeploy.

**Live verification status:** no public Railway URL, real DeepSeek result, or redeploy
persistence result is recorded in this repository state. Those checks require the
user-controlled Railway project and sealed secrets. Add a URL and success claims only
after they are actually verified.
