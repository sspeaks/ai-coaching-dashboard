# Project Context

- **Owner:** Seth Speaks
- **Project:** Evaluation and test coverage for an AI coaching dashboard
- **Stack:** Tests will cover the selected web, processing, AI, and NixOS stack
- **Created:** 2026-08-06T18:29:43.244-07:00
- **Research:** `my-barbershop-quartet-records-coaching-sessions-as.md`

## Learnings

- Product acceptance depends on coaching-intervention recall, unsupported-claim rate, attribution, timestamp accuracy, correction effort, privacy, and cost.
- Reviewer Rejection Protocol is binding: when you REQUEST CHANGES on a PR, the original author is locked out for one revision cycle; you nominate the fix agent.
- Caddy `route {}` rule: any handler combining `try_files` (rewrite) with `forward_auth` (capture) must wrap in `route {}` to prevent path rewriting from corrupting auth redirects (issue #28).
- Silent truncation is a defect class: any code that drops user-facing content must log + surface fallback. Appeared 4 times; now banned team-wide.
- Contrast pairing rule: `--muted` unsafe on elevated blue surfaces (e.g., `--brand-soft`); fix the pairing, never retune the token globally. Verified values elsewhere would break.

📌 Team update (2026-08-10T14:08:35-07:00): PR #5 member-first UI was independently typechecked, tested, built, and approved with no blocking findings — decided by Switch
📌 Team update (2026-08-11T01:20:00Z): Reviewer verdict mechanism: `gh pr review --approve/--request-changes` always refused (single account authors all PRs). Use `gh pr comment` with verdict in body instead — decided by Switch
📌 Team update (2026-08-11T01:20:00Z): Caddy `route {}` rule, Silent truncation ban, Contrast pairing rule codified as binding team decisions (rounds 11-18). Prevent repeat defect classes — decided by Morpheus, Rai
