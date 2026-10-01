# QA Remediation Progress

Baseline: `459fbf3` on `qa/remediation`; `822 passed in 13.28s`.

| Batch | Findings | Status | Claude session | Commit | Gates / review |
|---|---|---|---|---|---|
| 1. Backend guardrails | QA-06, QA-11, QA-18, QA-19, QA-29 | queued | — | — | — |
| 2. Scoped storage transactions | QA-01, QA-02, QA-15 | queued | — | — | — |
| 3. Crash durability and process locking | QA-07, QA-26, QA-28 | queued | — | — | — |
| 4. Backups, audit history, attachments | QA-03, QA-04, QA-16, QA-17, QA-27 | queued | — | — | — |
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

- None yet.
