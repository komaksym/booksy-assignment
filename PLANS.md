# Hardware Hub Delivery Roadmap

## Delivery Principle

Ship a complete vertical product and make the malformed seed the centerpiece of
the engineering story. Architecture exists only to keep the code understandable
for four small pull requests; explicit shortcuts are preferable to unfinished
infrastructure.

The executable plan lives in
[`docs/superpowers/plans/2026-07-22-hardware-hub-roadmap.md`](docs/superpowers/plans/2026-07-22-hardware-hub-roadmap.md).

## Artifacts

- [Slice 1 shell/auth specification](docs/superpowers/specs/2026-07-22-slice-1-shell-auth-design.md) — approved functional and visual contract for the first PR.
- [Slice 2 dirty-inventory specification](docs/superpowers/specs/2026-07-22-slice-2-dirty-inventory-design.md) — approved contract implemented on its review branch.
- [Slice 3 safe-rental specification](docs/superpowers/specs/2026-07-22-slice-3-safe-rental-design.md) — approved contract on its implementation branch.
- [Slice 3 implementation plan](docs/superpowers/plans/2026-07-22-slice-3-safe-rental-implementation.md) — test-first task sequence for the approved rental design.
- [Slice 4 audit/release specification](docs/superpowers/specs/2026-07-23-slice-4-audit-release-design.md) — approved deterministic/DeepSeek audit and verified-release contract.
- [Slice 4 audit/release completion plan](docs/superpowers/plans/2026-07-23-slice-4-audit-release-implementation.md) — acceptance, browser evidence, real DeepSeek, Railway persistence, and final-review sequence.
- [Reference UI mockup](docs/assets/hardware-hub-reference-ui.png) — visual
  direction for Slice 1's shell and Slice 2's dashboard/admin screens. It is a
  styling and layout reference, not an expansion of the MVP feature scope.

## Pull Request Sequence

| Slice | Branch | Reviewable outcome | Status |
| --- | --- | --- | --- |
| 1 | `codex/01-shell-auth` | Runnable app, visual foundation, signed-cookie login, admin-created users, health check, and minimal CI | Merged |
| 2 | `codex/02-dirty-inventory` | All eleven records preserved, anomalies visible, dashboard working, and admin CRUD complete | Merged |
| 3 | `codex/03-rental` | Guarded rent/return flow with ownership and visible history | Merged |
| 4 | `codex/04-audit-release` | Deterministic/DeepSeek audit, honest documentation, and one-worker Railway release | Completion validation in progress; live access and secrets still required |

No implementation duration, estimate, or timebox is part of this roadmap. Agents
work until the slice definition of done is satisfied and the PR is ready for
review; elapsed time must not be used to skip validation or narrow the contract.

```mermaid
flowchart LR
    S1["1. Shell + auth"] --> S2["2. Dirty inventory"]
    S2 --> S3["3. Rental"]
    S3 --> S4["4. Audit + handoff"]
```

## Mandatory Slice Workflow

Each slice still uses sub-agents, but orchestration must not become its own
project:

1. Start the branch from reviewed and merged `main`.
2. Give at least one implementation sub-agent a bounded feature or test task.
3. Use a fresh read-only sub-agent for one specification/quality review.
4. Parallelize only clearly disjoint files; the root agent owns integration.
5. Run the minimal gate, perform the slice's manual smoke check, and open one PR
   with a small Mermaid DAG.
6. Stop for user review before starting the next branch.

Sub-agents do not commit, push, or open PRs from the shared worktree.

## Minimal CI

One Ubuntu job runs on pull requests and pushes to `main`:

```text
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
```

There is no matrix, coverage service, mypy job, package-build job, Playwright,
preview environment, or deployment automation.

## Five Automated Tests That Matter

1. An admin creates a user; both can log in, while the ordinary user is denied an
   admin mutation.
2. All eleven source records survive idempotent loading; both duplicate IDs and
   the exact deterministic findings remain visible.
3. Canonical admin correction of source `10` clears its three repairable findings
   without rewriting the preserved raw source; unauthorized writes fail.
4. One unsafe item is blocked; a safe item completes the owner-only rent/return
   journey with history.
5. One LLM provider failure leaves deterministic audit results and inventory
   intact.

Tests can contain several assertions around one behavior. The goal is evidence,
not test-count inflation.

## Definition of Done

- The slice provides its advertised browser-visible behavior end to end.
- The relevant automated test passes, along with the complete small suite.
- Desktop and narrow-width manual smoke checks pass for changed screens.
- README and AI-development notes record actual shortcuts and corrections.
- The PR describes what works, what was deliberately omitted, validation, and a
  small dependency/data-flow DAG.
- The next slice remains untouched until review and merge.

## Explicitly Removed From the Implementation Contract

- persisted opaque sessions and session repositories;
- synchronizer CSRF tokens;
- global mutation coordinators and concurrency stress harnesses;
- a migration framework beyond idempotent first-run seed loading;
- hardened LLM redaction, streaming, byte-limit, or deadline infrastructure;
- runtime Railway volume-path guards and backup automation;
- automated browser testing;
- broad unit coverage for every helper or failure category.

These omissions are documented assessment trade-offs, not accidental gaps.

## Release Boundary

The user approved the detailed Slice 4 implementation specification. The code and
one-worker Railway contract can be completed on the review branch, but public
verification still requires the user-controlled Railway project, volume, funded
DeepSeek key, and sealed secrets. No URL or live success claim is recorded before
those checks actually pass.
