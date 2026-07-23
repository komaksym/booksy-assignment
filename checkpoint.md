# Slice 4 Audit and Release Checkpoint

## Repository state

- Repository: `komaksym/booksy-assignment`
- Branch: `codex/04-audit-release`
- Pull request: [#4 — feat(audit): complete MVP handoff](https://github.com/komaksym/booksy-assignment/pull/4)
- Base: merged Slice 3 `main` at `b1d0a959`
- Latest fully deployed release head before the final review fixes: `7456161`
- Pull request is open, mergeable, and ready for code review.

## Implemented contract

1. **Administrator audit surface**
   - `GET /admin/audit` renders fresh deterministic findings without calling a provider.
   - `POST /admin/audit/llm` is administrator-only and returns the same usable page on
     missing configuration, provider failure, or invalid model output.
   - Unauthenticated requests redirect to login; ordinary users receive `403`.

2. **Deterministic authority**
   - Existing `find_issues` rules remain the only operational safety authority.
   - Findings are rendered in a stable global table with severity, code, hardware link,
     source ID, and canonical rule message.
   - The audit routes do not write hardware documents.

3. **Allowlisted DeepSeek boundary**
   - One current snapshot includes all hardware records, including canonical-null rows.
   - Included fields are internal hardware ID, canonical fields, notes, legacy history,
     a legacy-assignee-presence boolean, and deterministic code/severity pairs.
   - Raw payloads, source IDs, users, emails, passwords, sessions, secrets, holders,
     rental history, and timestamps are excluded.
   - One configurable HTTPX chat-completions request uses a ten-second timeout, JSON
     output, disabled thinking, no retries, and a bounded response budget.

4. **Atomic model validation and fallback**
   - Pydantic forbids extra fields and validates UUIDs, severity values, and nonblank text.
   - Missing/empty content, malformed JSON, schema errors, non-stop completions,
     unexpected envelope shapes, and unknown hardware IDs discard the entire AI result.
   - Valid AI suggestions render separately under `AI suggestions — not operational
     decisions` and never mutate or govern inventory.

5. **Release handoff**
   - `railway.toml` pins one Uvicorn worker and `/health`.
   - README documents `/data/hardware-hub.json`, environment variables, setup,
     validation, manual product journey, shortcuts, security boundaries, AI disclosure,
     missing work, and the post-deployment checklist.

## Verification evidence

The implementation runner proved the new audit behavior failed before production code,
then completed this full package gate before committing the formatted implementation:

```text
uv lock --check
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
uv build
git diff --check
```

After independent review corrections, normal pull-request CI passed on release head
`7456161`:

```text
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
```

The final review additionally identified that the synchronous DeepSeek client needed
to run outside the single Uvicorn event loop. A concurrency regression now proves that
`/health` remains responsive during a blocked provider call. The known Starlette
`TestClient` deprecation warning remains pre-existing.

## Independent follow-up review

Fresh review found one Important issue: a provider response such as
`{"choices": [null]}` could raise `AttributeError` rather than returning the safe
fallback. Commit `868555f` expands the invalid-envelope boundary, and `637ebab` adds
focused regressions for that shape and non-stop completions. No remaining Critical or
Important code issue was found afterward.

## External verification complete

- Public service: `https://booksy-assignment-production.up.railway.app`
- `/health`, bootstrap login, user creation, all 11 records, source `10` correction,
  safe rent/return, deterministic audit, and one real DeepSeek response passed.
- Desktop and 390 px audit screenshots are stored in `docs/assets/` and linked from PR #4.
- Manual redeploy `d980b950-3e8c-4195-a12f-b00ffcf1055f` preserved the created user,
  corrected source `10`, and rental history on the mounted `/data` volume.

PR #4 remains open for explicit user review and must not be merged without approval.
