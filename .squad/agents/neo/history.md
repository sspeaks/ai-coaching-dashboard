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
