# QA Remediation Progress

Baseline: `459fbf3` on `qa/remediation`; `822 passed in 13.28s`.

| Batch | Findings | Status | Claude session | Commit | Gates / review |
|---|---|---|---|---|---|
| 1. Backend guardrails | QA-06, QA-11, QA-18, QA-19, QA-29 | accepted | `0cc1ed20-b22c-465a-b215-67b867a8361f` | `7e5b89b` | targeted 111 passed; full 877 passed; JS syntax passed; existing-test edits reviewed, no weakened assertions |
| 2. Scoped storage transactions | QA-01, QA-02, QA-15 | accepted | `958839d2-6204-44bb-ab7d-4139adba12cc` (resumed after turn cap) | `fcd7eeb` | focused 75 passed; full 898 passed; diff-check clean; route-scope scan and LRU/index tests passed |
| 3. Crash durability and process locking | QA-07, QA-26, QA-28 | accepted | direct implementation after Claude quota block | `26b0327` | journal recovery/import crash tests passed; OS lock tests passed; full 900 passed; diff-check clean |
| 4. Backups, audit history, attachments | QA-03, QA-04, QA-16, QA-17, QA-27 | accepted | direct implementation after Claude quota block | `57d760c` | full 901 passed; ZIP attachment round-trip, throttling, retention, legacy restore, and corrupt archive gates passed |
| 5. Pure GET and stale-write protection | QA-05, QA-10 | accepted | direct implementation | `5a0fdea` | board/duty GETs now preview on deep copies with `preparation_pending`; first mutations apply preparation; scoped revisions/stale 409 tests and full 901 passed |
| 6. Request and workflow reliability | QA-08, QA-09, QA-12, QA-13, QA-30 | partial | direct implementation | `c701a67`, `773479a` | 30s timeout, unknown mutation state, JSON 413/500, request sequencing, submit lock, authoritative combined daily mutation payload, and bulk pending-roster confirmation added; browser double-submit/timeout validation remains |
| 7. Frontend performance, UX, accessibility | QA-14, QA-20–QA-25 | partial | direct implementation | `de95d1d` | local-date generation, cached asset stamps, guarded localStorage, GET sequencing, submit locking, bounded combobox filtering, hover/focus service action rails, and an inert overlay sidebar added; full accessibility/register browser validation remains |
| 8. Final coherence and storage decision | all | partial | direct implementation | `42a1d4b` | benchmark harness added; isolated 1/30-day p95 smoke passed; Windows/HDD, browser 18-screen, 8-hour RSS, and power-loss validation remain target-environment work |

## Queue constraints

- Preserve split JSON unless the final target-hardware gate triggers the SQLite contingency.
- Never read or modify the production worktree's dirty `data/`, `data.json`, or `claude_test/`.
- One fresh Claude session and one reviewed local commit per batch; resumed sessions are rework only.
- No push. Fast-forward `refactor/data-models` only after all gates pass and no commit touches production data.

## Needs review

- Batch 1 browser confirmation path was not exercised; automated API and JS syntax gates passed.
- Batch 3 Windows-specific `msvcrt` path is covered by guarded implementation but not executable on this Linux host.
- Batch 6/7 broader UI workflow/accessibility work remains incomplete; release status stays NO-GO pending browser and target validation.
