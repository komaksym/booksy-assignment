# Slice 3 PR Review Checkpoint

## Repository state

- Repository: `komaksym/booksy-assignment`
- Branch: `codex/03-rental`
- Pull request: [#3 — feat(rental): add guarded circulation](https://github.com/komaksym/booksy-assignment/pull/3)
- Base: `main` at `9cc315c`
- Latest fully validated implementation/docs commit before this checkpoint refresh: `ec1cb6f`
- Next slice remains blocked until PR 3 is reviewed and merged.

## Review findings addressed

1. **Administrator held-item recovery**
   - The existing administrator edit POST can release an application-held canonical
     `In Use` item to `Available` or `Repair`.
   - The one full-record update applies validated metadata, clears the holder, appends
     an attributable `admin_release` event, and shares its UTC timestamp with
     `updated_at`.
   - Metadata-only edits preserve holder/history; malformed history, missing actor,
     held deletion, and inconsistent state changes remain rejected without writes.

2. **Return after newly discovered safety evidence**
   - A focused HTTP/storage regression rents a safe item, adds `battery swelling`
     through the administrator edit flow while the item remains held, proves the
     owner return succeeds, proves `SAFETY_RISK` activates after return, and proves
     the next rent returns `409` with the full document unchanged.

3. **Role-scoped status filtering**
   - Python supplies ordinary choices `Available`, `In Use`, `Repair`.
   - Administrators additionally receive `Needs correction`.
   - A crafted ordinary `status=Needs correction` request returns `400` and does not
     echo the concealed option into the page.

4. **Oversized rental test**
   - The former monolithic scenario is split into focused ordinary-view, rent,
     return/privacy, and safety-handoff tests with small shared helpers.
   - Existing authorization, storage, no-write, privacy, history-ordering, warning,
     multiple-holding, administrator-denial, and canonical-null assertions remain.
   - The specification, implementation plan, and AI development log now describe
     focused acceptance coverage rather than requiring one monolithic test function.

## Verification evidence

The one-time verification job for commit `ec1cb6f` completed all of the following
successfully before committing and pushing the final review corrections:

```text
uv sync --locked
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
uv build
git diff --check
```

The status-filter regression was first committed in a failing RED state. The later
role-scoped production change turned it green. The known Starlette `TestClient`
deprecation warning is unchanged.

## Fresh whole-branch review

A fresh read-only review of the branch from `9cc315c` through `ec1cb6f` found no
remaining Critical or Important issue in the rental service, administrator release,
role/visibility checks, status-filter concealment, history privacy, or focused
regressions.

## Remaining handoff steps

1. Mark Slice 3 PR-ready in `PLANS.md`.
2. Run the permanent CI workflow on the resulting exact head.
3. Update the PR body with current validation and review-correction details.
4. Reply to the inline test-refactor thread with explicit AI disclosure and resolve it.
5. Re-fetch review threads and stop for user review. Do not begin Slice 4 or merge PR 3
   without explicit user approval.
