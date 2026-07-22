# Slice 3 PR Review Checkpoint

## Repository state

- Repository: `/Users/koval/dev/booksy-assignment`
- Remote: `https://github.com/komaksym/booksy-assignment.git`
- Branch: `codex/03-rental`
- Pull request: [#3 — feat(rental): add guarded circulation](https://github.com/komaksym/booksy-assignment/pull/3)
- Current implementation HEAD before this checkpoint commit: `58f21f5`
- Base branch merge-base: `9cc315c`
- `PLANS.md` status: Slice 3 PR review fixes in progress

Root owns Git operations, pushes, PR updates, GitHub replies, and review-thread
resolution. After every successful commit, push immediately.

## Authoritative documents

Read these before continuing:

1. `PLANS.md`
2. `docs/superpowers/specs/2026-07-22-slice-3-safe-rental-design.md`
3. `docs/superpowers/plans/2026-07-22-slice-3-safe-rental-implementation.md`
4. `README.md`
5. `docs/ai-development-log.md`

Local ignored handoff artifacts:

- `.superpowers/sdd/pr-review-task-1-brief.md`
- `.superpowers/sdd/pr-review-task-1-report.md`
- `.superpowers/sdd/pr-review-task-1-rereview.diff`
- `.superpowers/sdd/pr-review-task-2-brief.md`

## Original PR review findings

The thread-aware review read found four actionable items:

1. Add an explicit administrator override for a held `In Use` item.
2. Prove that an owner return is never blocked by deterministic findings created
   during the rental, while the next rent is blocked.
3. Hide the administrator-only `Needs correction` filter from ordinary users.
4. Refactor the oversized `tests/test_rental.py` integration test.

GitHub currently has one unresolved inline thread on
`tests/test_rental.py`: “this test is enormous, and needs to be refactored.”
Do not resolve or reply until the refactor is implemented, reviewed, pushed, and CI
is green.

## Completed and pushed

### Administrator override — complete and review-clean

Commits:

- `f4e5dfe fix(rental): add admin release override`
- `58f21f5 fix(rental): harden admin release`

Implemented contract:

- Existing administrator edit POST may move application-held canonical `In Use`
  hardware to `Available` or `Repair`.
- The accepted edit performs one full-record TinyDB update that applies validated
  metadata, clears `holder_user_id`, appends one attributable event, and shares the
  event timestamp with `updated_at`.
- Exact event shape:

  ```json
  {
    "type": "admin_release",
    "user_id": "<administrator UUID>",
    "target_status": "Available",
    "occurred_at": "<aware UTC ISO-8601 timestamp>"
  }
  ```

- Metadata-only edits preserve the holder and history.
- Malformed non-list rental history and a missing release actor are rejected with no
  write.
- The old `update_hardware(table, id, form)` call shape remains valid for normal
  edits.
- Rejected edit pages re-read the current record before rendering; concurrent
  disappearance maps to `404`.
- Delete remains server-blocked while held. Python derives the delete action/reason;
  Jinja only renders it.
- History renders administrator release semantics without raw UUID exposure.
- The specification, implementation plan, README, and AI log reflect the clarified
  behavior.

Task review result: no remaining findings; Spec Compliance and Task Quality both
pass.

Fresh root verification after the fix:

```text
uv run pytest -q tests/test_inventory.py
12 passed, 1 existing TestClient deprecation warning

uv run ruff check .
All checks passed

git diff --check
passed
```

## Next task — not started

Use `.superpowers/sdd/pr-review-task-2-brief.md` as the exact task requirements.
Dispatch a fresh bounded implementer with no Git authority, then a fresh read-only
task reviewer.

Required behavior:

1. Add a focused journey that rents a safe item, adds editable notes containing
   `battery swelling` through the administrator edit HTTP flow while it remains
   held, proves the owner can return it, proves `SAFETY_RISK` becomes active, and
   proves the next rent returns `409` with zero writes.
2. Supply status choices from Python:
   - administrator: `Available`, `In Use`, `Repair`, `Needs correction`;
   - ordinary user: `Available`, `In Use`, `Repair`.
3. A crafted ordinary request for `status=Needs correction` must return a safe
   `400` and still not render that option.
4. Replace the 200+ line rental test with focused tests and small shared helpers,
   preserving every existing assertion and the Task 1 override coverage.
5. Update spec/plan wording that incorrectly requires one monolithic test function.

Follow strict test-first RED → GREEN, then refactor only while green. The task report
must include exact commands/results and a coverage-preservation checklist.

## Remaining completion sequence

1. Implement, validate, review, commit, and push Task 2.
2. Generate a whole-branch review package from `9cc315c` to the new HEAD.
3. Dispatch a fresh high-reasoning, read-only whole-branch reviewer.
4. Fix and re-review all Critical/Important findings.
5. Run the full gate:

   ```text
   uv lock --check
   uv sync --locked
   uv run ruff format --check .
   uv run ruff check .
   uv run pytest -q
   uv build
   git diff --check
   ```

6. Re-run the relevant browser smoke flow if UI behavior changed, and update the PR
   screenshot/body if the visible result materially changed.
7. Push every commit and watch `gh pr checks 3 --watch` to terminal success.
8. Reply to the inline test-refactor comment in its thread and resolve it only after
   the pushed diff and CI prove the fix. Summarize the three top-level findings in a
   concise PR comment if useful.
9. Re-fetch thread-aware PR comments and confirm no unresolved actionable review
   findings remain.
10. Set `PLANS.md` back to PR-ready and stop for user review; do not begin Slice 4.

## Guardrails

- Preserve the malformed eleven-record seed and immutable `raw_payload`.
- Ordinary users must never receive provenance, findings, raw holder IDs, user
  emails, or canonical-null records.
- Rent is critical-finding-gated; return is owner-gated and never finding-gated.
- Administrators cannot use ordinary rent/return routes.
- TinyDB support remains one process, one worker, one replica.
- No due dates, forced reassignment, reservations, LLM behavior, Railway work, or
  other Slice 4 scope.
- The existing Starlette `TestClient` deprecation warning is known and unchanged.
