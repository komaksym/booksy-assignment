# Slice 4 Audit and Release Checkpoint

## Repository state

- Repository: `komaksym/booksy-assignment`
- Branch: `codex/04-audit-release`
- Pull request: [#4 — feat(audit): complete MVP handoff](https://github.com/komaksym/booksy-assignment/pull/4)
- Base: merged Slice 3 `main` at `b1d0a959`
- Latest verified code head before this documentation refresh: `8a83d0d2`
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

After independent review corrections, normal pull-request CI passed on code head
`8a83d0d2`:

```text
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
```

A new exact-head CI run is required after this documentation-only checkpoint refresh.
The known Starlette `TestClient` deprecation warning remains pre-existing.

## Independent follow-up review

Fresh review found one Important issue: a provider response such as
`{"choices": [null]}` could raise `AttributeError` rather than returning the safe
fallback. Commit `868555f` expands the invalid-envelope boundary, and `637ebab` adds
focused regressions for that shape and non-stop completions. No remaining Critical or
Important code issue was found afterward.

## External verification still pending

The code is review-ready, but the complete live release cannot be claimed yet:

- no fresh desktop or narrow-viewport browser smoke or screenshot;
- no funded real DeepSeek request;
- no public Railway deployment URL;
- no Railway volume/redeploy persistence verification.

These require the user-controlled Railway project, mounted `/data` volume, provider key,
and sealed production secrets. Do not add a live URL or success claim until those checks
actually pass. Do not merge PR #4 without explicit user approval.
