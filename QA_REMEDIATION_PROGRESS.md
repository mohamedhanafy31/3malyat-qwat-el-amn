# QA Remediation Progress

Baseline: `459fbf3` on `qa/remediation`; `822 passed in 13.28s`.

| Batch | Findings | Status | Claude session | Commit | Gates / review |
|---|---|---|---|---|---|
| 1. Backend guardrails | QA-06, QA-11, QA-18, QA-19, QA-29 | accepted | `0cc1ed20-b22c-465a-b215-67b867a8361f` | pending | targeted 111 passed; full 877 passed; JS syntax passed; existing-test edits reviewed, no weakened assertions |
| 2. Scoped storage transactions | QA-01, QA-02, QA-15 | accepted | `958839d2-6204-44bb-ab7d-4139adba12cc` (resumed after turn cap) | pending | focused 75 passed; full 898 passed; diff-check clean; route-scope scan and LRU/index tests passed |
| 3. Crash durability and process locking | QA-07, QA-26, QA-28 | accepted | direct implementation after Claude quota block | pending | journal recovery/import crash tests passed; OS lock tests passed; full 900 passed; diff-check clean |
| 4. Backups, audit history, attachments | QA-03, QA-04, QA-16, QA-17, QA-27 | accepted | direct implementation after Claude quota block | pending | full 901 passed; ZIP attachment round-trip, throttling, retention, legacy restore, and corrupt archive gates passed |
| 5. Pure GET and stale-write protection | QA-05, QA-10 | queued | — | — | — |
| 6. Request and workflow reliability | QA-08, QA-09, QA-12, QA-13, QA-30 | queued | — | — | — |
| 7. Frontend performance, UX, accessibility | QA-14, QA-20–QA-25 | queued | — | — | — |
| 8. Final coherence and storage decision | all | queued | — | — | — |

## Queue constraints

- Preserve split JSON unless the final target-hardware gate triggers the SQLite contingency.
- Never read or modify the production worktree's dirty `data/`, `data.json`, or `claude_test/`.
- One fresh Claude session and one reviewed local commit per batch; resumed sessions are rework only.
- No push. Fast-forward `refactor/data-models` only after all gates pass and no commit touches production data.

## Needs review

- Batch 1 browser confirmation path was not exercised; automated API and JS syntax gates passed.
- Batch 3 Windows-specific `msvcrt` path is covered by guarded implementation but not executable on this Linux host.
