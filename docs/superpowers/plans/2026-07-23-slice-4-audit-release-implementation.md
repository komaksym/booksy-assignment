# Slice 4 Audit and Release Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Independently accept the committed Slice 4 audit implementation, produce browser evidence, verify one real DeepSeek request and a persistent Railway deployment, and make PR 4 truthfully review-ready.

**Architecture:** The existing branch already contains the test-first deterministic/DeepSeek audit implementation. This recovery plan does not duplicate it: first verify the committed artifact against the approved spec, then exercise the browser and external deployment boundaries. Any discovered behavior defect begins a new failing regression test before the smallest production fix.

**Tech Stack:** Python 3.12, FastAPI, Jinja, TinyDB, Pydantic, HTTPX, pytest, Ruff, uv, Playwright/browser tooling, DeepSeek chat completions, Railway Railpack and persistent volumes.

## Global Constraints

- Work only on `codex/04-audit-release`, based on merged Slice 3 `main`.
- Deterministic `find_issues(records, today)` output remains the only operational authority.
- Both audit routes are administrator-only, reload current hardware, and perform zero inventory writes.
- DeepSeek receives every current hardware record through the exact approved allowlist and receives no raw payload, source ID, user, email, holder, rental history, timestamp, cookie, session, or secret.
- Use `https://api.deepseek.com`, `deepseek-v4-flash`, JSON output, disabled thinking, one ten-second request, no retries, and atomic response rejection.
- Never print, render, log, commit, paste into chat, or place in a URL any API key, session secret, or bootstrap password.
- Railway runs one service, one replica, one Uvicorn worker, and mounts its TinyDB volume at `/data`.
- A real successful DeepSeek result and a data-survives-redeploy check are required before claiming the live release verified.
- Subagents do not commit, push, update the PR, deploy externally, or manage Git; the root agent owns integration and all external mutations.
- After each root-owned commit, push immediately.

---

### Task 1: Accept the Existing Audit Implementation

**Files:**
- Inspect: `docs/superpowers/specs/2026-07-23-slice-4-audit-release-design.md`
- Inspect: `src/hardware_hub/audit.py`
- Inspect: `src/hardware_hub/app.py`
- Inspect: `src/hardware_hub/config.py`
- Inspect: `src/hardware_hub/rules.py`
- Inspect: `src/hardware_hub/templates/audit.html`
- Inspect: `src/hardware_hub/templates/base.html`
- Inspect: `src/hardware_hub/static/app.css`
- Inspect: `tests/test_audit.py`
- Inspect: `tests/test_audit_provider_envelope.py`
- Inspect: `pyproject.toml`
- Inspect: `uv.lock`
- Inspect: `.env.example`
- Inspect: `railway.toml`

**Interfaces:**
- Consumes: `find_issues(records: list[dict[str, Any]], today: date) -> tuple[Finding, ...]`, TinyDB hardware documents, `Settings.llm_base_url`, `Settings.llm_model`, and `Settings.llm_api_key`.
- Produces: an evidence-backed accept/fix decision for the branch at its exact Git head; if a defect exists, a focused regression-and-fix task with no unrelated refactor.

- [ ] **Step 1: Record the exact acceptance target**

Run:

```bash
git rev-parse HEAD
git merge-base origin/main HEAD
git diff --check origin/main...HEAD
git status --short
```

Expected: the head is the current PR 4 commit, the merge base is current merged
`origin/main`, diff check is silent, and the worktree has no unexplained change.

- [ ] **Step 2: Run the focused audit regressions**

Run:

```bash
uv run pytest -q tests/test_audit.py tests/test_audit_provider_envelope.py
```

Expected: access control, deterministic fallback, exact snapshot privacy,
valid-response rendering, malformed response, non-stop completion, unknown ID, and
full-document non-mutation tests all pass.

- [ ] **Step 3: Run the complete clean gate**

Run:

```bash
uv lock --check
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
uv build
git diff --check
```

Expected: every command exits `0`; the current suite reports `28 passed` with only
the already documented Starlette TestClient deprecation warning.

- [ ] **Step 4: Dispatch one bounded read-only acceptance reviewer**

Give a fresh reviewer the approved specification and a review package for
`origin/main...HEAD`. Require two explicit verdicts:

```text
Specification compliance: APPROVED or REJECTED
Code quality: APPROVED or REJECTED
```

The reviewer must check route authorization/status, same-snapshot deterministic and
AI results, allowlist exclusions, strict provider-envelope handling, no-write paths,
template boundaries, runtime HTTPX dependency, and the Railway contract.

- [ ] **Step 5: Handle any rejection test-first**

If the reviewer reports a Critical or Important defect, dispatch one bounded fixer
with the full finding list. The fixer must:

```text
1. add one focused failing regression per behavior defect;
2. run it and record the expected RED failure;
3. implement the smallest fix;
4. rerun the focused tests and report exact output;
5. leave commits, pushes, and PR changes to the root agent.
```

Generate a new review package and require the same reviewer to approve both verdicts
before continuing. If no defect exists, make no production-code change.

---

### Task 2: Produce Local Browser Evidence

**Files:**
- Create: `docs/assets/slice-4-audit-desktop.png`
- Create: `docs/assets/slice-4-audit-narrow.png`
- Inspect: `src/hardware_hub/templates/audit.html`
- Inspect: `src/hardware_hub/static/app.css`

**Interfaces:**
- Consumes: the real FastAPI application with an isolated temporary TinyDB file and intentionally missing LLM configuration.
- Produces: desktop and narrow-width screenshots showing deterministic findings, the disabled DeepSeek action, and the existing application shell without exposing credentials.

- [ ] **Step 1: Start an isolated local server**

Use non-production-only test credentials and a temporary database outside the
repository. Do not reuse the developer database.

```bash
ENVIRONMENT=development \
TINYDB_PATH=/private/tmp/hardware-hub-slice4-smoke.json \
SESSION_SECRET=local-slice4-smoke-secret-not-for-production \
BOOTSTRAP_ADMIN_EMAIL=admin@slice4.local \
BOOTSTRAP_ADMIN_PASSWORD=local-slice4-smoke-password \
LLM_BASE_URL= \
LLM_MODEL= \
LLM_API_KEY= \
uv run uvicorn --app-dir src hardware_hub.app:app --host 127.0.0.1 --port 8014
```

Expected: Uvicorn listens on `127.0.0.1:8014`, `/health` returns success, and no
DeepSeek configuration is present.

- [ ] **Step 2: Exercise the administrator browser journey**

In the browser:

```text
1. open http://127.0.0.1:8014/login;
2. log in as admin@slice4.local;
3. open Audit;
4. verify all deterministic findings render in one global table;
5. verify hardware names link to administrator detail pages;
6. verify “Request DeepSeek second opinion” is disabled;
7. verify the page identifies LLM_BASE_URL, LLM_MODEL, and LLM_API_KEY as missing.
```

Expected: no model call occurs and inventory remains unchanged.

- [ ] **Step 3: Capture desktop evidence**

Set the viewport to `1440x1000` and save the full-page audit screenshot exactly as:

```text
docs/assets/slice-4-audit-desktop.png
```

Expected: title, deterministic authority copy, finding table, and disabled model
panel are legible; no secret or raw assignee email appears.

- [ ] **Step 4: Capture narrow evidence**

Set the viewport to `390x844`, reload `/admin/audit`, and save exactly as:

```text
docs/assets/slice-4-audit-narrow.png
```

Expected: the shell remains usable, the action panel stays visible, and the global
table scrolls within its container instead of widening the page.

- [ ] **Step 5: Verify the image files and stop the server**

Run:

```bash
file docs/assets/slice-4-audit-desktop.png docs/assets/slice-4-audit-narrow.png
git diff --check
```

Expected: both files are valid PNG images and diff check is silent. Stop only the
server process started in Step 1.

- [ ] **Step 6: Commit and push browser evidence**

```bash
git add docs/assets/slice-4-audit-desktop.png docs/assets/slice-4-audit-narrow.png
git commit -m "docs(audit): add Slice 4 browser evidence" -m "Captures the administrator audit at desktop and narrow widths, showing deterministic findings and the safe missing-provider state without exposing credentials."
git push
```

---

### Task 3: Verify DeepSeek and Publish Railway

**Files:**
- Inspect: `railway.toml`
- Inspect: `.env.example`
- Modify after verification: `README.md`
- Modify after verification: `PLANS.md`

**Interfaces:**
- Consumes: user-controlled authenticated Railway access; a funded DeepSeek key entered directly as a sealed Railway variable; sealed production session/bootstrap values; the repository's one-worker Railpack contract.
- Produces: one public HTTPS Railway domain, a successful real DeepSeek audit, and proof that a known TinyDB change survives one redeploy.

- [ ] **Step 1: Establish user-controlled prerequisites without disclosing them**

The user performs the secret entry directly. Confirm only presence, never value:

```text
Railway account/project access: present
Persistent volume capability: present
LLM_API_KEY: present and funded
SESSION_SECRET: present and long random value
BOOTSTRAP_ADMIN_EMAIL: present
BOOTSTRAP_ADMIN_PASSWORD: present and non-example value
```

Do not continue to a live-success claim if any item is absent.

- [ ] **Step 2: Create or link the Railway service**

Use the GitHub repository `komaksym/booksy-assignment`, branch
`codex/04-audit-release`, and the committed `railway.toml`. Configure exactly one
service and one replica. Generate one public domain only for that service.

Expected runtime command:

```text
uv run uvicorn --app-dir src hardware_hub.app:app --host 0.0.0.0 --port $PORT --workers 1
```

- [ ] **Step 3: Attach persistent storage and variables**

Attach one volume at `/data`, then set:

```text
ENVIRONMENT=production
TINYDB_PATH=/data/hardware-hub.json
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

Enter `SESSION_SECRET`, `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`, and
`LLM_API_KEY` as sealed variables. Do not echo their values in command output or
copy them into documentation.

- [ ] **Step 4: Verify the public vertical journey**

Against the generated HTTPS domain:

```text
1. GET /health and require success;
2. log in as the bootstrap administrator;
3. create one ordinary user;
4. verify all 11 dirty records and deterministic findings;
5. correct source 10 and record one harmless canonical value for persistence;
6. complete one safe ordinary-user rent and owner return;
7. open Audit and submit one real DeepSeek request;
8. require a valid separate “AI suggestions — not operational decisions” result.
```

Expected: deterministic output stays visible, the real model result validates, and
no inventory mutation originates from either audit route.

- [ ] **Step 5: Verify persistence across redeploy**

Redeploy the same service once without deleting or remounting the volume. After the
new deployment becomes healthy, log back in and verify the known source `10`
canonical change and created ordinary user still exist.

Expected: data persists from `/data/hardware-hub.json`; only one application worker
and one replica are active.

- [ ] **Step 6: Record only verified release facts**

Replace README's pending live-status paragraph with:

```markdown
**Live verification status:** verified on `<public Railway HTTPS URL>`. `/health`,
bootstrap login, user creation, the 11-record inventory, source `10` correction,
safe rent/return, deterministic audit, and one real DeepSeek response passed. The
known canonical correction and created user remained present after one redeploy,
confirming the `/data` volume mount.
```

Here `<public Railway HTTPS URL>` means the exact domain produced and tested in
Step 4; it is not guessed or filled before verification. Update `PLANS.md` Slice 4
status to `Live verification complete; PR ready for final review`.

- [ ] **Step 7: Commit and push verified release facts**

```bash
git add README.md PLANS.md
git commit -m "docs(release): record verified Railway deployment" -m "Records the tested public service, successful DeepSeek audit, complete product smoke journey, and persistence of known data across one Railway redeploy."
git push
```

---

### Task 4: Final Review and PR Handoff

**Files:**
- Inspect: every file in `origin/main...HEAD`
- Modify externally: GitHub PR 4 body

**Interfaces:**
- Consumes: exact final branch diff, full validation output, both browser images, live URL, DeepSeek success, persistence proof, and any task-review reports.
- Produces: one truthful ready-for-review PR with no unresolved Critical or Important finding.

- [ ] **Step 1: Re-run the final repository gate**

```bash
uv lock --check
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
uv build
git diff --check
git status --short --branch
```

Expected: all checks pass and the branch is clean and synchronized with
`origin/codex/04-audit-release`.

- [ ] **Step 2: Dispatch a fresh whole-branch read-only reviewer**

Generate a review package from `git merge-base origin/main HEAD` through `HEAD`.
The reviewer must compare the final diff to the approved spec and report Critical,
Important, and Minor findings with file/line evidence. Require explicit spec and
quality verdicts. Any Critical or Important finding returns to the test-first fix
loop and re-review before PR handoff.

- [ ] **Step 3: Update PR 4 with exact evidence**

Keep the existing Summary and Mermaid DAG. Replace the pending release-boundary
claims with the verified public URL, real DeepSeek result, redeploy-persistence
result, final gate output, and embedded desktop screenshot:

```markdown
![Slice 4 administrator audit](https://raw.githubusercontent.com/komaksym/booksy-assignment/codex/04-audit-release/docs/assets/slice-4-audit-desktop.png)
```

Do not claim checks that did not run and do not include any secret-bearing output.

- [ ] **Step 4: Confirm final GitHub state and stop**

Verify PR 4 is open, non-draft, mergeable, and CI is successful at the exact branch
head. Present the PR URL, validation evidence, live URL, screenshots, reviewer
verdict, and any remaining non-blocking limitations to the user. Stop for final
user review; do not merge the PR.
