# Project Context

- **Owner:** Seth Speaks
- **Project:** AI coaching dashboard for barbershop quartet recordings
- **Stack:** Local-first processing preferred; optional AI APIs; web-facing backend; NixOS deployment
- **Created:** 2026-08-06T18:29:43.244-07:00
- **Research:** `my-barbershop-quartet-records-coaching-sessions-as.md`

## Learnings

- Quartet singing, overlap, and distant microphones make speech recognition and speaker attribution unreliable; coach speech and timestamp linkage are the priority.
- 2026-08-07T10:32:42.057-07:00: Built the OpenAI-backed extraction gateway as a separate FastAPI service matching the evidence API's `http_json` contract, with bearer auth, structured JSON output, contract-model validation, citation normalization/drop rules, and Nix container/module wiring.
- 2026-08-07T12:12:18.011-07:00: Reviewer feedback tightened extraction observability: fabricated-citation drops now log reason/topic/segment IDs without transcript text, responses include rejected counts, and support checks now avoid trivial one-word observed-result passes while documenting confidence as uncalibrated.
- Silent truncation is a defect class: any code that drops user-facing content (themes, ledger entries, moments) must log + surface fallback where possible. Appeared 4 times; now banned team-wide (rules 11-18).
- Reviewer Rejection Protocol: when Switch REQUEST CHANGES on your PR, you are locked out for one revision cycle; Morpheus nominated as fix agent for PR #30 two-pass consolidation.

📌 Team update (2026-08-10T14:08:35-07:00): Future extraction/disclosure work must account for the non-local pipeline: audio goes to Speakr/possibly ASR, while transcript, ledger, and note text may leave via the configured OpenAI-compatible gateway — decided by Trinity and Fact Checker
📌 Team update (2026-08-11T01:20:00Z): Silent truncation ban codified: any code path dropping user-facing content MUST log warning + attempt fallback. Third instance caught in #30 extraction: unclaimed pre_group IDs → singleton fallback themes — decided by Rai, Morpheus

## 2026-08-11T02:05:00Z — Rounds 19-21: Board Clear Summary

**Round 19 — Review PR #33 (Morpheus consolidation fix):**
- Rejected: consolidation truncation log had zero test coverage.
- Established binding rule: Guard branches MUST be proven to fire via caplog; untested log lines have no evidence.

**Round 21 — Re-review PR #33 (Trinity caplog fix):**
- Approved after Trinity added caplog test.
- Mutation analysis confirms test captures guard behavior.
- Note: pytest mutations unverifiable locally (Python 3.10 < 3.11).

**Team Decisions Binding All Agents:**
- Concurrent agents MUST use separate git worktrees. Shared checkout caused false test count this round (14 vs 21).
- Guards must be proven to fire via caplog assertions.
- Schema-boundary mismatches are recurring — validate receiving constraint vs. sending.
- Truncate user-facing text with `[:N-3] + "…"`, never bare slice.
- Eval fixtures must default to failure (full matrix) not permission (enumerated list).
- 2026-08-12T17:49:51.136-07:00: Issue #54 phone playback revision found the native `<audio controls>` was rendered on phone (`controls=true`, `display:block`) but Chromium gave it 0px height in the column mobile audio section until CSS assigned an explicit 2.5rem control height; added focused Playwright/Nix assertion and screenshots for 390x844 and 360x800, including mini-playhead rendered-width checks at 1:14 and 2:12.

📌 Team update (2026-08-12T14:57:07.018-07:00): Revision lockouts and PR #49 showed fresh agents need to re-verify the real baseline and clean-checkout path, not inherit prior claims. Always branch from origin/main, verify `git diff origin/main...HEAD --stat`, and test dynamic behavior directly. — decided by Ralph/Morpheus review loop
📌 Team update (2026-08-12T17:49:51.136-07:00): Board cleared after PRs #55-#62 and issues #53/#44/#42/#40/#54. Mandatory lesson: user-visible UI requires BOTH code/behavior review and Mouse screenshot review; green CI and correct DOM/data flow can still hide zero-height controls. Switch PR #62 now guards hidden/zero-size/offscreen interactive controls on phone, and mutation testing is expected for behavior guards. Merge P0/overlapping PRs first, then re-check mergeability and CI after every merge; prefer stable test ids/role queries over exact copy for guards.
