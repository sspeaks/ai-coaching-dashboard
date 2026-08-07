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
