# Hardware Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved Hardware Hub MVP as five sequential pull requests, each providing a testable end-to-end outcome and stopping for user review before the next begins.

**Architecture:** FastAPI route handlers render Jinja pages and HTMX fragments while auth, inventory, rental, and audit services own behavior. Repositories isolate TinyDB, and one application-scoped async lock serializes every TinyDB mutation. Deterministic rules protect inventory transitions; a read-only OpenAI-compatible adapter enriches admin audits without becoming a dependency of core behavior.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, HTMX, TinyDB, Pydantic Settings, pwdlib/Argon2id, HTTPX, pytest, Playwright, Ruff, mypy, uv, GitHub Actions, Railway.

## Global Constraints

- Execute exactly one slice at a time from freshly reviewed and merged `main`.
- Use `codex/` branch names from the table in `PLANS.md`; do not stack PRs.
- Use TDD for domain behavior: write the failing test, run it and observe the
  expected failure, implement the smallest behavior, then rerun it.
- Keep route handlers thin. Presentation code must not own authorization,
  validation, transitions, persistence, or LLM decisions.
- Route every TinyDB write through one application-scoped `asyncio.Lock`.
  TinyDB rewrites the shared JSON document, so this includes users, sessions,
  bootstrap, seed import, hardware, and history.
- Never hold the mutation lock across an LLM network call. Snapshot under the
  lock, release it, then call the provider.
- Store no secrets in Git, logs, rendered errors, LLM requests, or tests.
- Use temporary TinyDB paths in all tests. No test may call a live provider.
- Escape all seed and user-supplied text through Jinja autoescaping.
- Update `docs/AI_DEVELOPMENT_LOG.md` and `docs/PROMPT_TRAIL.md` in the slice
  where a decision or correction occurs; do not reconstruct the history later.
- Each slice must pass:

  ```bash
  uv sync --locked --all-extras
  uv run ruff format --check .
  uv run ruff check .
  uv run mypy src
  uv run pytest -q
  uv build
  ```

- Each PR body must use `Summary`, `Validation`, `Risks / Notes`, and
  `Breaking changes`, and must include the slice-specific Mermaid DAG below.
- After the PR opens, stop for user review. Start no file from the next slice.

## Standard Sub-Agent Orchestration

For every slice, the root agent performs this sequence:

- [ ] Create the branch from updated `main` and record the exact acceptance
  contract in the active task.
- [ ] Spawn at least two implementation sub-agents with `fork_turns="none"`,
  self-contained prompts, and disjoint file ownership. Use domain/repository,
  web/templates, and tests/docs as the preferred seams.
- [ ] Integrate each completed subtask before assigning work that depends on it.
- [ ] Spawn two fresh read-only reviewers in parallel: one for specification and
  test coverage, one for code quality and security.
- [ ] Resolve every high-confidence finding and rerun the full validation gate.
- [ ] Have only the root agent stage and commit. Use a concise conventional
  subject plus a body explaining the reason, key detail, and known limitation.
- [ ] Push the branch, open one PR, include the required DAG, and stop.

Parallel edits to a shared file are forbidden. Parallel read-only review is
encouraged because it provides speed without worktree conflicts.

---

## Slice 1: Walking Skeleton, Persistence Boundary, and Minimal CI

**Branch:** `codex/01-foundation-ci`

**Outcome:** A reviewer can clone the repository, install it, run a FastAPI
service, receive a safe health response, verify an injectable TinyDB path, and
see the same checks run in one GitHub Actions job.

**Agent allocation:** One agent owns Task 1.1. After that contract lands, a
storage agent owns Task 1.2 while a CI/documentation agent owns Task 1.3 on
non-overlapping files; the root integrates their `app.py`/config touchpoints
sequentially if either needs them.

### Task 1.1: Package and application factory

**Files:**

- Create: `pyproject.toml`
- Create: `uv.lock`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `src/hardware_hub/__init__.py`
- Create: `src/hardware_hub/app.py`
- Create: `src/hardware_hub/config.py`
- Create: `src/hardware_hub/templates/base.html`
- Create: `src/hardware_hub/templates/home.html`
- Create: `src/hardware_hub/static/app.css`
- Create: `tests/conftest.py`
- Create: `tests/test_health.py`

- [ ] Configure Python `>=3.12,<3.13` and the `src` package layout. Add
  `fastapi`, `uvicorn[standard]`, `jinja2`, `tinydb`, `pydantic-settings`, and
  direct `httpx` support for Starlette's test client as runtime dependencies;
  add `pytest`, `pytest-asyncio`, `ruff`, and `mypy` as development dependencies.
  Generate and commit `uv.lock`. Enable Ruff security rules; allow assertion
  rule `S101` only in tests.
- [ ] Write and run the failing health test:

  ```python
  def test_health_exposes_only_liveness(client: TestClient) -> None:
      response = client.get("/health")

      assert response.status_code == 200
      assert response.json() == {"status": "ok"}
      assert "TINYDB_PATH" not in response.text
  ```

  Run: `uv run pytest tests/test_health.py -q`
  Expected: fail because `hardware_hub.app` does not exist.

- [ ] Implement `Settings` and the application factory with explicit dependency
  injection:

  ```python
  class Settings(BaseSettings):
      environment: Literal["development", "test", "production"] = "development"
      tinydb_path: Path = Path("var/hardware-hub.json")

  def create_app(settings: Settings | None = None) -> FastAPI:
      resolved = settings or Settings()
      app = FastAPI(title="Hardware Hub")
      app.state.settings = resolved
      return app

  app = create_app()
  ```

- [ ] Mount static files, configure Jinja templates with autoescape, render the
  minimal home page, and keep `/health` independent of data/config details.
- [ ] Run the health test and the formatting/lint/type checks.
- [ ] Commit with subject `feat(core): add FastAPI walking skeleton` and a body
  describing the injectable settings boundary.

### Task 1.2: Shared TinyDB runtime and production-volume guard

**Files:**

- Create: `src/hardware_hub/storage.py`
- Create: `src/hardware_hub/lifespan.py`
- Create: `tests/test_storage.py`
- Create: `tests/test_config.py`
- Modify: `src/hardware_hub/app.py`
- Modify: `src/hardware_hub/config.py`

- [ ] Write failing tests proving that each app instance owns one database and
  one mutation lock, test data goes to `tmp_path`, the database closes on
  shutdown, repository writes outside the current task's mutation context fail,
  overlapping writes to two dummy tables never enter concurrently, and
  production rejects a database path outside the Railway volume:

  ```python
  def test_production_requires_volume_path(tmp_path: Path) -> None:
      settings = Settings(
          environment="production",
          tinydb_path=tmp_path / "ephemeral.json",
          railway_volume_mount_path=Path("/data"),
      )

      with pytest.raises(ValueError, match="persistent Railway volume"):
          validate_storage_path(settings)
  ```

- [ ] Implement these narrow runtime interfaces:

  ```python
  class Storage:
      @asynccontextmanager
      async def mutation(self) -> AsyncIterator[None]: ...

      def require_mutation_owner(self) -> None:
          """Raise unless the current asyncio task owns the mutation lock."""

  def open_storage(settings: Settings) -> Storage: ...
  def validate_storage_path(settings: Settings) -> None: ...
  ```

- [ ] Keep the TinyDB handle private to `Storage`; expose read access to
  repositories and require every repository insert/update/remove method to call
  `require_mutation_owner()`. Track ownership with the current asyncio task so a
  lock held by a different request cannot satisfy the assertion.

- [ ] Validate the production path only when `environment == "production"`.
  Require both `RAILWAY_VOLUME_MOUNT_PATH` and a `TINYDB_PATH` contained beneath
  it. Compare fully resolved absolute paths, and test `..` traversal, a sibling
  prefix such as `/data-backup`, and a symlink inside the mount that escapes it.
  Never print either resolved path in an HTTP response.
- [ ] Fail closed when Railway runtime markers such as `RAILWAY_ENVIRONMENT` or
  `RAILWAY_PROJECT_ID` exist but `ENVIRONMENT` is not `production`; test this so
  an omitted variable cannot silently disable the persistent-path guard.
- [ ] Open storage and create required directories during FastAPI lifespan, not
  at module import or in a Railway pre-deploy command.
- [ ] Run: `uv run pytest tests/test_storage.py tests/test_config.py -q`
- [ ] Commit with subject `feat(storage): isolate TinyDB runtime` and a body
  explaining the single-process/all-writes locking boundary.

### Task 1.3: CI, Railway configuration, and contributor setup

**Files:**

- Create: `.github/workflows/ci.yml`
- Create: `.env.example`
- Create: `docs/railway.env.example`
- Create: `railway.toml`
- Create: `README.md`
- Create: `docs/AI_DEVELOPMENT_LOG.md`
- Create: `docs/PROMPT_TRAIL.md`
- Create: `tests/test_deployment_contract.py`

- [ ] Write a deployment-contract test that loads `railway.toml` and asserts
  `/health`, `$PORT`, and `--workers 1` are present in the deploy configuration;
  also assert `.env.example` uses local `ENVIRONMENT=development` while
  `docs/railway.env.example` names `ENVIRONMENT=production`,
  `TINYDB_PATH=/data/hardware-hub.json`, the expected platform-provided
  `RAILWAY_VOLUME_MOUNT_PATH=/data`, and secret variable names without values.
- [ ] Add one Ubuntu CI job for pull requests and pushes to `main`, using one
  Python version and exactly the global validation commands. Give the workflow
  only `contents: read`; pin `actions/checkout` and `astral-sh/setup-uv` to these
  reviewed immutable commits, disable persisted checkout credentials, install
  uv `0.11.16`, and let setup-uv provision Python 3.12:

  ```yaml
  permissions:
    contents: read

  steps:
    - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      with:
        persist-credentials: false
    - uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
      with:
        version: "0.11.16"
        python-version: "3.12"
        enable-cache: true
  ```

  Do not add a build matrix, coverage service, preview deploy, or release job.
- [ ] Configure Railway with Railpack and this runtime contract:

  ```toml
  [build]
  builder = "RAILPACK"

  [deploy]
  startCommand = "uv run uvicorn hardware_hub.app:app --host 0.0.0.0 --port $PORT --workers 1"
  healthcheckPath = "/health"
  healthcheckTimeout = 100
  ```

- [ ] Put local non-secret defaults in `.env.example` and the production contract
  with empty secret values in `docs/railway.env.example`. Document that Railway
  must set `ENVIRONMENT=production`, attach a volume at `/data`, expose its
  platform mount variable, and set `TINYDB_PATH=/data/hardware-hub.json`;
  `railway.toml` cannot attach a volume or provision secrets.
- [ ] Add local setup/run/test instructions and initialize the implementation
  status, shortcut, next-step, AI-tooling, data-strategy, prompt-trail, and
  correction sections required by the assignment.
- [ ] Run the full validation gate from a clean environment.
- [ ] Commit with subject `ci: add minimal validation gate` and a body describing
  what CI deliberately omits.

### Slice 1 acceptance and PR

- [ ] Confirm `/health` returns exactly `{"status":"ok"}`.
- [ ] Confirm no test writes outside `tmp_path`.
- [ ] Confirm production startup fails for a missing/mismatched volume path.
- [ ] Run the service locally and smoke-check home and health pages.
- [ ] Open the PR with this DAG:

  ```mermaid
  flowchart LR
      Env["Environment"] --> Settings["Validated settings"]
      Settings --> App["FastAPI lifespan"]
      App --> Store["TinyDB + shared lock"]
      App --> Health["Safe /health"]
      CI["GitHub Actions"] --> Checks["lint + types + tests + build"]
  ```

- [ ] Stop for user review and merge.

---

## Slice 2: Admin-Provisioned Authentication

**Branch:** `codex/02-admin-auth`

**Outcome:** A bootstrap administrator can log in, create an account, and that
new user can log in; unknown or inactive accounts cannot gain access and no
public registration path exists.

**Agent allocation:** A domain/security agent owns Task 2.1, then separate web
and account-flow agents own Tasks 2.2 and 2.3 in order because both touch auth
routes. Fresh spec and security reviewers run in parallel afterward.

### Task 2.1: Auth domain, repositories, and cryptography

**Files:**

- Create: `src/hardware_hub/auth/__init__.py`
- Create: `src/hardware_hub/auth/models.py`
- Create: `src/hardware_hub/auth/repository.py`
- Create: `src/hardware_hub/auth/security.py`
- Create: `src/hardware_hub/auth/service.py`
- Create: `tests/auth/test_service.py`
- Create: `tests/auth/test_bootstrap.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/hardware_hub/config.py`
- Modify: `src/hardware_hub/lifespan.py`

- [ ] Add `pwdlib[argon2]` as a runtime dependency and refresh `uv.lock`.
- [ ] Write failing service tests for normalized unique email, Argon2id hashing,
  idempotent bootstrap, missing/partial first-admin configuration, generic
  authentication failure, session expiry, logout, inactive-user invalidation,
  and raw-token non-persistence. Add concurrent `User@Example.com` versus
  `user@example.com` creation and assert exactly one succeeds, plus lock probes
  proving user insert, session insert, and session removal all execute inside
  the current task's `Storage.mutation()` context.
- [ ] Fix the clock and token generator in tests through injected callables. Use
  this public contract:

  ```python
  @dataclass(frozen=True, slots=True)
  class IssuedSession:
      raw_token: str
      csrf_token: str
      expires_at: datetime

  class AuthService:
      async def bootstrap_admin(self) -> None: ...
      async def create_user(self, actor: User, command: CreateUser) -> User: ...
      async def authenticate(self, email: str, password: str) -> IssuedSession: ...
      async def resolve_session(self, raw_token: str) -> AuthContext | None: ...
      async def logout(self, raw_token: str) -> None: ...
  ```

- [ ] Persist only `sha256(raw_token)` for the session. Store a separate random
  synchronizer CSRF token on the server and compare submitted tokens with
  `secrets.compare_digest`.
- [ ] Generate every raw session token from 32 cryptographically random bytes
  and issue a new token for every successful login.
- [ ] Use a fixed dummy Argon2id hash when the email is unknown so unknown and
  bad-password requests follow the same password-verification path.
- [ ] Put bootstrap email/password in optional settings. Reject a half-configured
  pair. When an admin already exists, do nothing even if credentials are absent;
  when no admin exists, require both values and create exactly one admin. Execute
  bootstrap under the shared mutation lock during lifespan.
- [ ] In `create_user`, `authenticate`, and `logout`, acquire
  `Storage.mutation()`, re-read uniqueness/user/session state, then perform the
  write. Add one cross-table overlap test proving a user write and session write
  serialize even though they use different repositories.
- [ ] Run: `uv run pytest tests/auth/test_service.py tests/auth/test_bootstrap.py -q`
- [ ] Commit with subject `feat(auth): add account and session services` and a
  body explaining opaque-token storage and bootstrap idempotence.

### Task 2.2: Login/logout HTTP flow and protection dependencies

**Files:**

- Create: `src/hardware_hub/auth/dependencies.py`
- Create: `src/hardware_hub/auth/routes.py`
- Create: `src/hardware_hub/web/__init__.py`
- Create: `src/hardware_hub/web/csrf.py`
- Create: `src/hardware_hub/templates/login.html`
- Create: `src/hardware_hub/templates/partials/auth_error.html`
- Create: `tests/auth/test_routes.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/hardware_hub/app.py`
- Modify: `src/hardware_hub/templates/base.html`

- [ ] Add `python-multipart` as a runtime dependency for FastAPI form parsing
  and refresh `uv.lock`.
- [ ] Write failing route tests proving unknown email, inactive account, and bad
  password return the same visible error and emit no `Set-Cookie`; `/register`
  returns 404; expired/logged-out sessions cannot reach protected pages; and
  logout rejects a missing, wrong, or cross-session CSRF token. Also prove a
  cross-origin or token-less login POST cannot install a session.
- [ ] Add `current_user`, `require_user`, and `require_admin` dependencies backed
  by `resolve_session`.
- [ ] Expose `GET /login`, `POST /login`, CSRF-protected `POST /logout`, and a
  protected `GET /` hub landing page. Redirect successful login to `/`; Slice 3
  adds `/hardware` without making this slice depend on that future route.
- [ ] On `GET /login`, generate a pre-session double-submit token, render it as a
  hidden field, and set it in a short-lived `__Host-login-csrf` cookie with
  Secure, HttpOnly, SameSite=Strict, and Path=/ attributes. On `POST /login`,
  require constant-time equality between cookie and form values before password
  verification, then clear/rotate the token. This is separate from the persisted
  authenticated-session CSRF token.
- [ ] On successful login set exactly:

  ```python
  response.set_cookie(
      key="__Host-session",
      value=issued.raw_token,
      secure=True,
      httponly=True,
      samesite="strict",
      path="/",
      max_age=8 * 60 * 60,
  )
  ```

- [ ] On logout delete the stored session and clear the cookie with matching
  attributes. Do not expose raw tokens in logs or response bodies.
- [ ] Test using an HTTPS `TestClient` base URL so Secure-cookie behavior is
  exercised rather than bypassed.
- [ ] Run: `uv run pytest tests/auth/test_routes.py -q`
- [ ] Commit with subject `feat(auth): protect sessions and routes` and a body
  describing cookie and generic-error behavior.

### Task 2.3: Admin-created account UI and CSRF enforcement

**Files:**

- Create: `src/hardware_hub/templates/admin/users.html`
- Create: `src/hardware_hub/templates/admin/user_form.html`
- Create: `src/hardware_hub/web/responses.py`
- Create: `tests/auth/test_admin_accounts.py`
- Modify: `src/hardware_hub/auth/routes.py`
- Modify: `src/hardware_hub/static/app.css`
- Modify: `README.md`
- Modify: `docs/AI_DEVELOPMENT_LOG.md`
- Modify: `docs/PROMPT_TRAIL.md`

- [ ] Write failing tests for admin account creation, created-user login,
  normalized duplicate rejection, non-admin 403, missing/wrong/cross-session
  CSRF rejection, and no database change after every rejected request.
- [ ] Render the session's CSRF token in every authenticated mutation form and
  verify it before service invocation.
- [ ] Implement admin-only `GET /admin/users` and `POST /admin/users` for the
  user list/create page. Return stable 422 form errors for validation and 403
  for authorization; do not leak whether an email exists through login
  behavior.
- [ ] Update implementation status and record the actual auth prompts,
  trade-offs, and corrections made during this slice.
- [ ] Run all auth tests and the full validation gate.
- [ ] Commit with subject `feat(accounts): add admin provisioning flow` and a
  body explaining that initial passwords are the deliberate MVP shortcut.

### Slice 2 acceptance and PR

- [ ] Inspect TinyDB and confirm passwords are Argon2id hashes and session values
  equal the SHA-256 of issued tokens rather than the raw tokens.
- [ ] Manually complete bootstrap admin login, account creation, user login, and
  logout; verify the cookie flags in the browser.
- [ ] Open the PR with this DAG:

  ```mermaid
  flowchart LR
      Admin["Bootstrap admin"] --> Login["Generic login"]
      Login --> Session["Hashed opaque session"]
      Session --> Guard["User/admin + CSRF guards"]
      Guard --> Create["Admin creates account"]
      Create --> User["Created user can log in"]
  ```

- [ ] Stop for user review and merge.

---

## Slice 3: Inventory, Lossless Seed Import, and Deterministic Rules

**Branch:** `codex/03-inventory-rules`

**Outcome:** Users can browse, sort, and filter all valid visible hardware;
administrators can manage it; the exact dirty dataset is preserved and its
deterministic anomalies are visible and reusable as rental guards.

**Agent allocation:** Fresh agents own seed/model, deterministic rules,
inventory service, and UI tasks in dependency order. Once implementation is
integrated, data-integrity and web/security reviewers run concurrently.

### Task 3.1: Hardware schema and lossless seed import

**Files:**

- Create: `src/hardware_hub/inventory/__init__.py`
- Create: `src/hardware_hub/inventory/models.py`
- Create: `src/hardware_hub/inventory/repository.py`
- Create: `src/hardware_hub/inventory/seed.py`
- Create: `src/hardware_hub/data/hardware_seed.json`
- Create: `tests/inventory/test_seed.py`
- Modify: `src/hardware_hub/lifespan.py`

- [ ] Transcribe the assignment's exact 11 JSON objects into
  `hardware_seed.json`, including both source-ID `4` records, missing source ID
  `8`, `Appel`, `22-05-2023`, the blank brand, null date, `Unknown`, battery
  swelling, and liquid-damage text.

  ```json
  [
    {"id": 1, "name": "Apple iPhone 13 Pro Max", "brand": "Apple", "purchaseDate": "2021-11-23", "status": "Available"},
    {"id": 2, "name": "Apple MacBook Pro 13", "brand": "Apple", "purchaseDate": "2021-12-20", "status": "In Use"},
    {"id": 3, "name": "Razer Basilisk V2", "brand": "Razer", "purchaseDate": "2021-06-05", "status": "Repair"},
    {"id": 4, "name": "SAMSUNG Galaxy S21", "brand": "Samsung", "purchaseDate": "2021-11-23", "status": "Available"},
    {"id": 5, "name": "Dell XPS 15 9510", "brand": "Dell", "purchaseDate": "2022-03-15", "status": "Available", "notes": "Battery swelling, do not issue without service."},
    {"id": 6, "name": "Logitech MX Master 3", "brand": "Logitech", "purchaseDate": "2027-10-10", "status": "Available"},
    {"id": 7, "name": "Sony WH-1000XM4", "brand": "Sony", "purchaseDate": "2022-01-12", "status": "In Use", "assignedTo": "j.doe@booksy.com"},
    {"id": 4, "name": "Duplicate ID Test Laptop", "brand": "Lenovo", "purchaseDate": "2023-01-01", "status": "Repair"},
    {"id": 9, "name": "iPad Pro 12.9", "brand": "Appel", "purchaseDate": "22-05-2023", "status": "Available"},
    {"id": 10, "name": "Unknown Device", "brand": "", "purchaseDate": null, "status": "Unknown"},
    {"id": 11, "name": "MacBook Air M2", "brand": "Apple", "purchaseDate": "2023-08-01", "status": "Available", "history": "Returned by user with liquid damage. Keyboard sticky."}
  ]
  ```
- [ ] Write failing tests proving first startup imports 11 records, second startup
  imports zero, both source-ID `4` records have distinct internal UUIDs, and each
  stored `raw_payload` is value-equivalent to its source object.
- [ ] Model canonical status as `Available | In Use | Repair | None`. Parse only
  ISO `YYYY-MM-DD` dates; preserve invalid values in `raw_payload` and use `None`
  canonically. Never silently correct brands, dates, status, notes, or history.
- [ ] Seed only when the hardware table is empty and run import inside the shared
  mutation lock during app lifespan.
- [ ] Run: `uv run pytest tests/inventory/test_seed.py -q`
- [ ] Commit with subject `feat(inventory): import dirty seed losslessly` and a
  body explaining source IDs versus internal IDs.

### Task 3.2: Deterministic findings and rentability contract

**Files:**

- Create: `src/hardware_hub/inventory/holder_resolution.py`
- Create: `src/hardware_hub/inventory/rules.py`
- Create: `tests/inventory/test_rules.py`

- [ ] Write table-driven failing tests for these exact seed findings and stable
  rule contracts:

  | Code | Severity | Affected source records |
  | --- | --- | --- |
  | `DUPLICATE_SOURCE_ID` | warning | both records with source ID `4` |
  | `FUTURE_PURCHASE_DATE` | warning | source `6`, with clock fixed to `2026-07-22` |
  | `UNRESOLVED_HOLDER` | critical | sources `2` and `7` |
  | `SAFETY_RISK` | critical | sources `5` and `11` |
  | `INVALID_PURCHASE_DATE` | warning | source `9` |
  | `MISSING_BRAND` | warning | source `10` |
  | `MISSING_PURCHASE_DATE` | warning | source `10` |
  | `INVALID_STATUS` | critical | source `10` |

- [ ] Expose pure deterministic interfaces shared by admin display and Slice 4:

  ```python
  @dataclass(frozen=True, slots=True)
  class RuleContext:
      today: date
      holder_resolvable: Mapping[UUID, bool]

  def audit_inventory(
      items: Sequence[Hardware],
      *,
      context: RuleContext,
  ) -> list[Finding]: ...

  def evaluate_rentability(
      item: Hardware,
      findings: Sequence[Finding],
  ) -> Rentability:
      """Return allowed=False plus stable reason codes for blocking findings."""
  ```

- [ ] Make archived, non-Available, null-status, unresolved legacy In Use,
  battery-swelling, and liquid-damage records non-rentable. Only deterministic
  critical findings can block; no LLM type appears in this module.
- [ ] Also cover warning-level `MISSING_NAME` and critical
  `CONTRADICTORY_ASSIGNMENT` findings on synthetic records so every
  deterministic rule from the approved design has a stable code even when the
  supplied seed does not exercise it.
- [ ] Build `holder_resolvable` by matching a legacy `assignedTo` email to an
  active normalized account or by resolving an application holder ID. Test that
  creating active `j.doe@booksy.com` removes source `7`'s unresolved-holder
  finding without exposing that email in the finding; source `2` remains
  unresolved.
- [ ] Confirm `Appel` remains unchanged. It may later be an LLM suggestion, but
  it is not a deterministic mutation.
- [ ] Run: `uv run pytest tests/inventory/test_rules.py -q`
- [ ] Commit with subject `feat(inventory): add deterministic safety rules` and a
  body explaining why rentability is independent of the LLM.

### Task 3.3: Inventory service and admin mutations

**Files:**

- Create: `src/hardware_hub/inventory/service.py`
- Create: `tests/inventory/test_service.py`

- [ ] Write failing service tests for list/filter/sort, create/edit, repair/clear,
  archive, stable validation errors, role enforcement, immutable history, and
  unchanged state after rejected operations.
- [ ] Use these service boundaries:

  ```python
  class InventoryService:
      async def list_items(self, query: InventoryQuery, actor: User) -> list[Hardware]: ...
      async def create_item(self, command: CreateHardware, actor: User) -> Hardware: ...
      async def update_item(self, item_id: UUID, command: UpdateHardware, actor: User) -> Hardware: ...
      async def set_repair(self, item_id: UUID, repair: bool, actor: User) -> Hardware: ...
      async def archive(self, item_id: UUID, actor: User) -> Hardware: ...
  ```

- [ ] Define command ownership explicitly: `CreateHardware` accepts name, brand,
  purchase date, notes, and initial `Available` or `Repair` status only.
  `UpdateHardware` accepts canonical name/brand/date/notes/legacy-history
  corrections and may set status only when correcting an imported null status,
  again only to `Available` or `Repair`. `raw_payload`, internal/source IDs,
  holder, archive timestamp, and embedded events are never command fields;
  `In Use` is reachable only through the rental service.
- [ ] Re-read and validate inside the shared mutation lock. Non-admin mutations,
  `In Use` repair/archive attempts, and invalid commands must leave canonical
  fields, immutable raw payload, and history byte-for-byte unchanged.
- [ ] Hide archived and canonical-null-status hardware from normal users while
  retaining both for admin inspection. Append actor-attributed
  create/update/repair/archive events.
- [ ] Run: `uv run pytest tests/inventory/test_service.py -q`
- [ ] Commit with subject `feat(inventory): add guarded management service` and a
  body describing revalidation under the mutation lock.

### Task 3.4: Dashboard and admin hardware UI

**Files:**

- Create: `src/hardware_hub/inventory/routes.py`
- Create: `src/hardware_hub/templates/inventory/dashboard.html`
- Create: `src/hardware_hub/templates/inventory/_table.html`
- Create: `src/hardware_hub/templates/inventory/detail.html`
- Create: `src/hardware_hub/templates/admin/hardware.html`
- Create: `src/hardware_hub/templates/admin/hardware_form.html`
- Create: `tests/inventory/test_routes.py`
- Modify: `src/hardware_hub/app.py`
- Modify: `src/hardware_hub/templates/base.html`
- Modify: `src/hardware_hub/static/app.css`
- Modify: `README.md`
- Modify: `docs/AI_DEVELOPMENT_LOG.md`
- Modify: `docs/PROMPT_TRAIL.md`

- [ ] Write failing route tests for authentication, admin-only mutations, CSRF,
  sort/filter query parameters, archived/null-status visibility, Jinja escaping,
  assignee display, history display, and equal item ordering/content between
  full-page and HTMX table responses.
- [ ] Implement server-side filtering and sorting by name, brand, purchase date,
  and status. HTMX requests replace `_table.html`; ordinary requests render the
  same table inside `dashboard.html`.
- [ ] Use these explicit routes: `GET /hardware`;
  `GET /hardware/{item_id}` for status and attributable immutable history;
  `GET /admin/hardware`; `GET /admin/hardware/new`; `POST /admin/hardware`;
  `GET /admin/hardware/{item_id}/edit`; and CSRF-protected POST routes ending in
  `/update`, `/repair`, `/clear-repair`, and `/archive` for existing items.
- [ ] Show invalid imported values and rule findings to administrators instead
  of coercing or hiding them. Provide add/edit/repair/archive forms with inline
  errors and post-success redirects or fragment refreshes.
- [ ] Include the required assignee column. Normal users see `You`, `Assigned`,
  or `Unresolved legacy assignment`; admins may also see the resolvable account
  email. Never render the raw legacy assignee email for an unresolved record.
- [ ] Update implementation status and record the actual data/rules prompts,
  trade-offs, and corrections made during this slice.
- [ ] Run all inventory tests and the full validation gate.
- [ ] Commit with subject `feat(inventory): add dashboard and admin controls` and
  a body describing full-page/HTMX equivalence.

### Slice 3 acceptance and PR

- [ ] Manually verify all 11 records, both duplicate IDs, filters, sorting,
  admin edit/repair/archive, narrow layout, and escaped dirty text.
- [ ] Confirm rejected admin operations cause no database changes.
- [ ] Open the PR with this DAG:

  ```mermaid
  flowchart LR
      Seed["Exact dirty seed"] --> Canonical["Canonical + raw records"]
      Canonical --> Rules["Deterministic findings"]
      Rules --> Guard["Reusable rentability"]
      Canonical --> Service["Inventory service"]
      Service --> UI["Dashboard + admin HTMX"]
  ```

- [ ] Stop for user review and merge.

---

## Slice 4: Atomic Rent and Return Lifecycle

**Branch:** `codex/04-rental-engine`

**Outcome:** A created user can rent safe available hardware and return their
own item; impossible or unauthorized transitions are rejected atomically and
the complete action history remains attributable.

**Agent allocation:** Separate agents own the state machine, HTTP/UI controls,
and browser journey in that order; concurrency and authorization reviewers then
run in parallel.

### Task 4.1: Rental state machine and concurrency tests

**Files:**

- Create: `src/hardware_hub/rentals/__init__.py`
- Create: `src/hardware_hub/rentals/service.py`
- Create: `tests/rentals/test_service.py`

- [ ] Write failing tests for success, already-rented conflict, repair, null
  status, archived, sources `5` and `11`, own return, another user's return
  denial, admin force-return, and unchanged state/history for every failure.
- [ ] Write the concurrency test before implementation:

  ```python
  first_task = asyncio.create_task(service.rent(item_id, first_user))
  await repository.first_read_reached.wait()

  second_task = asyncio.create_task(service.rent(item_id, second_user))
  await asyncio.sleep(0)
  assert repository.read_count == 1  # second request is blocked by the lock

  repository.release_first_read.set()
  first, second = await asyncio.gather(first_task, second_task, return_exceptions=True)

  assert sum(isinstance(result, Hardware) for result in (first, second)) == 1
  assert sum(isinstance(result, StateConflict) for result in (first, second)) == 1
  stored = await repository.get(item_id)
  event = stored.events_of("rent").one()
  assert event.actor_user_id == stored.current_holder_user_id
  ```

- [ ] Back this test with an async pausing repository fake whose first read waits
  on the two events shown above. Without the mutation lock the second request
  reaches the same pre-write state and `read_count == 1` fails; a merely
  sequential `asyncio.gather` test is not sufficient evidence.
- [ ] Implement `rent` and `return_item` so each acquires the shared lock,
  re-reads the item, recomputes deterministic rentability, validates actor and
  state, then persists canonical state plus one embedded event in one repository
  operation.
- [ ] A user may return only their own rental. An admin may force-return and the
  event details must distinguish the override without exposing secrets.
- [ ] Returning clears holder, sets `Available`, and appends exactly one event.
- [ ] Run: `uv run pytest tests/rentals/test_service.py -q`
- [ ] Commit with subject `feat(rentals): add atomic rent and return flow` and a
  body explaining the single-process concurrency guarantee.

### Task 4.2: Rental controls and stable HTTP failures

**Files:**

- Create: `src/hardware_hub/rentals/routes.py`
- Create: `src/hardware_hub/templates/inventory/_rental_action.html`
- Create: `src/hardware_hub/templates/inventory/_action_error.html`
- Create: `tests/rentals/test_routes.py`
- Modify: `src/hardware_hub/inventory/routes.py`
- Modify: `src/hardware_hub/templates/inventory/_table.html`
- Modify: `src/hardware_hub/templates/inventory/detail.html`
- Modify: `src/hardware_hub/app.py`

- [ ] Write failing direct-request tests proving hidden buttons cannot bypass
  authorization, state, deterministic safety, or CSRF guards.
- [ ] Map domain outcomes consistently: unauthenticated to redirect/401 by
  content negotiation, forbidden to 403, missing to 404, invalid form to 422,
  and stale/impossible state to 409. HTMX failures replace only the action area.
- [ ] Expose only CSRF-protected `POST /hardware/{item_id}/rent` and
  `POST /hardware/{item_id}/return`; there are no state-changing GET routes.
- [ ] Render Rent only for apparently rentable items, Return only for the current
  renter, and Force return only for admins. Keep the backend authoritative.
- [ ] Render rent/return events on the existing hardware detail page with action,
  timestamp, and actor attribution; route tests must see those events after the
  corresponding POST.
- [ ] Run route tests and the full validation gate.
- [ ] Commit with subject `feat(rentals): add guarded HTMX controls` and a body
  describing domain-to-HTTP error mapping.

### Task 4.3: Browser user journey

**Files:**

- Create: `tests/e2e/conftest.py`
- Create: `tests/e2e/test_user_journey.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/AI_DEVELOPMENT_LOG.md`
- Modify: `docs/PROMPT_TRAIL.md`

- [ ] Add `pytest-playwright` to the development dependencies, refresh
  `uv.lock`, and mark browser tests `e2e`. In `tests/e2e/conftest.py`, start the
  app on an ephemeral localhost port with a temporary TinyDB path and stop it
  deterministically after the test session.
- [ ] Write one browser test that starts with the bootstrap admin, creates a
  normal user, logs out, logs in as that user, rents source `1`, verifies `In
  Use`, returns it, and verifies `Available` plus rent/return history.
- [ ] Install only Chromium in CI with
  `uv run playwright install --with-deps chromium`. Keep this test in the same
  job and reuse the temporary TinyDB fixture; do not add a browser matrix.
- [ ] Update implementation status and record the actual rental/E2E prompts,
  trade-offs, and corrections made during this slice.
- [ ] Run: `uv run pytest tests/e2e/test_user_journey.py -q`
- [ ] Run the complete global validation gate after the dependency, lockfile,
  workflow, documentation, and E2E changes.
- [ ] Commit with subject `test(e2e): cover account and rental journey` and a
  body identifying the one cross-slice path it protects.

### Slice 4 acceptance and PR

- [ ] Run the concurrency test repeatedly and confirm one holder/one rent event.
- [ ] Manually rent/return at desktop and narrow widths and inspect history.
- [ ] Open the PR with this DAG:

  ```mermaid
  flowchart LR
      Request["Rent/return request"] --> Lock["Shared mutation lock"]
      Lock --> Read["Re-read current item"]
      Read --> Rules["Auth + state + safety guards"]
      Rules --> Write["State + one history event"]
      Write --> Fragment["HTMX action result"]
  ```

- [ ] Stop for user review and merge.

---

## Slice 5: Hybrid Auditor and Release Handoff

**Branch:** `codex/05-auditor-release`

**Outcome:** An administrator can run a read-only audit that always returns
deterministic findings and, when configured, exactly one validated LLM
enrichment request. Provider failure cannot corrupt data or block the core app,
and the same PR completes the explicitly approved public Railway release.

**Agent allocation:** Separate agents own the LLM adapter, audit service/UI, and
release documentation in dependency order. Privacy/security and deployment
reviewers run in parallel; only the root performs external publication actions.

### Task 5.1: Allowlisted LLM contract and adapter

**Files:**

- Create: `src/hardware_hub/audit/__init__.py`
- Create: `src/hardware_hub/audit/models.py`
- Create: `src/hardware_hub/audit/llm.py`
- Create: `tests/audit/test_llm.py`
- Modify: `src/hardware_hub/config.py`
- Modify: `.env.example`
- Modify: `docs/railway.env.example`

- [ ] Write failing adapter tests for exactly one request; entirely missing and
  every partially configured three-variable provider combination; production
  HTTP/non-HTTPS rejection; HTTP 4xx/5xx; transport error; a slow-drip response
  crossing a 10-second wall-clock deadline; a response over 256 KiB; malformed
  JSON; invalid severity; unknown hardware IDs; and secret-free errors/logs. Use
  HTTPX `MockTransport`; never call a live endpoint.
- [ ] Define an outbound DTO by allowlist, not by serializing storage models:

  ```python
  class AuditItem(BaseModel):
      hardware_id: UUID
      name: str | None
      brand: str | None
      purchase_date: date | None
      status: HardwareStatus | None
      notes: str | None
      legacy_history: str | None
      has_resolvable_holder: bool

  class AuditRequest(BaseModel):
      items: list[AuditItem]
      deterministic_findings: list[OutboundDeterministicFinding]
  ```

- [ ] Pass every outbound string, including names, brands, notes, legacy history,
  deterministic evidence, and explanations, through one redactor for email
  addresses, authorization headers, common password/token/key assignments, and
  known provider-key formats. Prove fixtures embedding those values serialize
  only redaction markers. The DTO never contains user ID, session fields, raw
  holder identity, configuration values, or the full raw payload.
- [ ] Use this exact OpenAI-compatible wire contract: treat `LLM_BASE_URL` as a
  versioned base such as `https://api.openai.com/v1`; POST once to
  `{LLM_BASE_URL.rstrip('/')}/chat/completions` with `model`, `temperature: 0`, a
  fixed system message, and `AuditRequest.model_dump_json()` as the user message.
  Read `choices[0].message.content` as one JSON object shaped
  `{"findings": [...]}`. Do not use provider tools or grant write capability.
- [ ] Parse the provider response into strict Pydantic findings with known
  hardware IDs, bounded text lengths, at most 100 findings, and
  `critical | warning | info`. Reject the entire LLM result on schema failure
  and return a typed provider warning.
- [ ] Configure `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL`; interpolate the
  API key only into the Authorization header and never into exceptions shown to
  users. Missing, partial, or production-non-HTTPS configuration performs zero
  HTTP requests and yields a non-blocking provider warning.
- [ ] Wrap the streamed HTTPX request in an outer `asyncio.timeout(10)` wall-clock
  deadline as well as HTTPX operation timeouts; abort once cumulative response
  bytes exceed 256 KiB. A peer that trickles bytes cannot extend the total
  deadline.
- [ ] Run: `uv run pytest tests/audit/test_llm.py -q`
- [ ] Commit with subject `feat(audit): add safe LLM adapter` and a body
  describing the allowlisted payload and fail-closed output validation.

### Task 5.2: Read-only audit orchestration and admin UI

**Files:**

- Create: `src/hardware_hub/audit/service.py`
- Create: `src/hardware_hub/audit/routes.py`
- Create: `src/hardware_hub/templates/admin/audit.html`
- Create: `src/hardware_hub/templates/admin/_audit_results.html`
- Create: `tests/audit/test_service.py`
- Create: `tests/audit/test_routes.py`
- Modify: `src/hardware_hub/app.py`
- Modify: `src/hardware_hub/templates/base.html`
- Modify: `src/hardware_hub/static/app.css`

- [ ] Write failing tests proving non-admin denial, deterministic results with no
  provider config, exactly one adapter call when configured, visible provider
  warning on failure, and identical inventory snapshots before/after every
  audit outcome.
- [ ] Under the mutation lock, read a consistent inventory snapshot and compute
  anonymous holder-resolvability. Release the lock before the HTTP request.
- [ ] Always run `audit_inventory` with the same `RuleContext` contract from
  Slice 3 and preserve its complete result. Put its redacted deterministic
  findings into `AuditRequest`, then merge valid LLM findings for display only;
  never feed them into rentability or repository writes.
- [ ] Use `GET /admin/audit` for the empty/explanatory page and CSRF-protected
  `POST /admin/audit` as the only operation that invokes the adapter.
- [ ] Render findings grouped by deterministic/AI source and severity, with
  evidence, explanation, recommended action, provider warning, and admin edit
  links. Protect the trigger with admin role and CSRF.
- [ ] Run all audit tests and verify a simulated 10-second timeout does not hold
  the mutation lock by completing an independent write during the pending mock.
- [ ] Commit with subject `feat(audit): add hybrid inventory review` and a body
  explaining deterministic continuity and read-only AI behavior.

### Task 5.3: Release documentation and Railway verification

**Files:**

- Modify: `README.md`
- Modify: `docs/AI_DEVELOPMENT_LOG.md`
- Modify: `docs/PROMPT_TRAIL.md`
- Create: `docs/DEPLOYMENT.md`
- Create: `docs/RELEASE_CHECKLIST.md`
- Modify: `tests/test_deployment_contract.py`

- [ ] Finalize the assignment-required README sections: fully implemented,
  shortcuts/hacks with why/future, partial or missing work, top three next-day
  priorities, setup, tests, architecture, demo credentials strategy, and live
  link status. Before external approval it must truthfully say the demo is not
  yet published; update it with the verified URL on this same branch before the
  PR is approved and merged.
- [ ] Record at least one concrete AI correction: the initial hardware-only lock
  idea was unsafe because TinyDB rewrites the shared file, so implementation
  serializes every TinyDB mutation.
- [ ] Document Railway setup exactly: one service/replica, one worker, one
  `/data` volume, platform-provided `RAILWAY_VOLUME_MOUNT_PATH=/data`,
  `ENVIRONMENT=production`, `TINYDB_PATH=/data/hardware-hub.json`, bootstrap
  secrets, LLM secrets, a generated public domain, health check, startup seeding,
  persistence/redeploy check, and rollback note. Do not use a pre-deploy command
  because the volume is unavailable there.
- [ ] Document platform limits honestly: a mounted volume prevents horizontal
  replicas; volume-backed redeploys have brief downtime; Railway health checks
  gate deployment startup rather than continuously monitoring the service; code
  rollback does not roll back the TinyDB file, so back up the volume before a
  risky release.
- [ ] Add a release checklist for full tests, `git diff --check`, dependency
  review, `gitleaks git . --log-opts="--all" --redact --exit-code 1` after
  fetching all remote refs/tags, manual review of publishable seed/AI-log/prompt
  content for PII or proprietary data, manual auth/inventory/rental/audit smoke
  tests, persistent data after redeploy, generated-domain health verification,
  and a recorded exact release SHA.
- [ ] Run the full validation gate and the complete browser test on the final
  candidate.
- [ ] Commit with subject `docs(release): add deployment and assessment handoff`
  and a body listing verified behavior and explicit MVP limits.

### Slice 5 acceptance and PR

- [ ] Confirm no live LLM call occurs in tests and no provider error exposes the
  configured key.
- [ ] Confirm inventory data is identical before and after successful, failed,
  and malformed audits.
- [ ] Run the complete release checklist except the external publication and
  Railway-launch steps.
- [ ] Open Slice 5 as a draft PR with this DAG:

  ```mermaid
  flowchart LR
      Trigger["Admin audit trigger"] --> Snapshot["Locked inventory snapshot"]
      Snapshot --> Rules["Deterministic findings"]
      Snapshot --> DTO["Allowlisted anonymous DTO"]
      DTO --> LLM["One bounded LLM call"]
      LLM --> Validate["Strict output validation"]
      Rules --> Report["Read-only report"]
      Validate --> Report
      Failure["Provider failure"] --> Report
  ```

- [ ] Stop for user review and request explicit release approval while this same
  PR remains open. Do not publish or deploy merely because code review passes.
- [ ] After approval, fetch all remote refs and tags, run the full-history secret
  scan at the exact release SHA, and present the seed (including its
  internal-looking email), AI log, and prompt trail for the user's explicit
  public-content confirmation before changing repository visibility.
- [ ] On confirmation, make the repository public and configure Railway to deploy
  the Slice 5 branch with one replica/worker, the `/data` volume, production
  variables/secrets, no pre-deploy command, and a generated public domain.
- [ ] Verify `/health`, bootstrap/admin flow, user rent/return, deterministic and
  provider audit paths, secret-free errors, and TinyDB persistence across a
  redeploy. Create a manual Railway volume backup before the redeploy test.
- [ ] Put the verified public URL and release evidence into README/docs on this
  same branch, push the same PR, rerun CI and the release checklist, and request
  the user's final PR approval.
- [ ] After the user merges PR 5, switch Railway's source branch to `main` (or
  redeploy merged `main`) and verify the same domain and persisted data. No sixth
  code/documentation PR is expected.

## Final Plan Review Checklist

- [ ] All assignment pillars map to a slice and acceptance test.
- [ ] No later slice is required for an earlier PR's advertised outcome.
- [ ] Auth precedes every business-data route.
- [ ] Deterministic safety rules precede and are reused by rentals.
- [ ] The browser journey lands with the complete rent/return feature.
- [ ] LLM output is read-only and does not participate in rental guards.
- [ ] Every TinyDB mutation uses the shared lock; the LLM call does not hold it.
- [ ] No task contains placeholder paths, undecided interfaces, or live secrets.
- [ ] Every slice ends in full validation, one PR, and a user review gate.
