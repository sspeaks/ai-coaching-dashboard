# Morpheus History

## Standing context
- Project: AI coaching dashboard for barbershop quartet recordings, owned by Seth Speaks.
- Morpheus is Lead Architect / merge-gate reviewer. Preserve architecture, sequencing, and release gates.

## Durable architecture and review rules
- Treat Authentik-branded login 500s before oauth2-proxy callback as IdP incidents first; confirm with Authentik server/worker logs.
- Concurrent agents must use separate git worktrees. Shared checkout state previously caused wrong-branch commits, stacked branches, and misleading test counts.
- Any handler combining Caddy `try_files` with `forward_auth` must be wrapped in `route {}` so auth sees the original path.
- Do not silently drop user-facing content. Dropped themes, ledger items, or moments must log and surface a fallback.
- Guard branches must be proven to fire via assertions/log capture and mutation; untested warnings are not evidence.
- Schema-boundary flows need receiving-model constraint checks for length, enum, optionality, and bounds. Truncate user-facing text with `[:N-3] + "…"`, never a bare slice.
- Eval fixtures should default to failure: generate full distinct-pair matrices and list explicit allowed merges, not the reverse.
- For contrast fixes, fix unsafe token pairings (for example `--muted` on elevated blue consent/status/error surfaces), not global tokens that pass elsewhere.

## UX governance learned 2026-08-12
- Mouse's screenshot-only UX review findings #36-#44 were filed for Link; #36/#37 blocked v0.4.0. Trinity was locked out by reviewer protocol, Link owned remediation.
- User-visible `type:ux` PRs require two gates before merge: code/behavior review and Mouse screenshot review. PR #45 showed screenshots can miss dynamic hardcoded playhead bugs; PR #57 showed code review/CI can miss zero-height visible controls.
- Merge P0 and overlapping UX PRs first. After each merge, refresh every remaining PR's mergeability and CI; stale bases surfaced as mismatched test counts and immediate conflicts.
- Screenshot approval does not prove dynamic correctness, and code tests do not prove pixel usability. Keep both gates mandatory.
- Copy renames can break literal-string tests; prefer stable `data-testid` hooks and role-based queries for behavior guards.

## Key 2026-08-12 board-clear work
- Resolved local/origin `main` divergence by verifying local commits 7f2fe04, 64638fd, and e017a92 were redundant via upstream UX PRs, then resetting local main to origin/main while preserving `.squad/` state. This ended scope-leaked diffs and confusing CI/test-count drift.
- Reviewed and merged PR #55 (stable failed-state UX capture wait) and PR #56 (deletion confirmation must defer during pending provider-write sections).
- Reviewed and merged PR #57 for compact summary source playback; mutation-tested playhead/pause behavior, but merged before Mouse completed and later accepted this as a process failure.
- Reviewed PR #59 first-run guidance, refreshed stale base, verified real drag/drop and progress behavior, mutation-tested upload behavior, and merged after Mouse approval/green CI.
- Reviewed PR #60 optional note-review controls, verified native `<details>` kept controls mounted and accessible, mutation-tested `aria-describedby`, and merged after Mouse approval/green CI.
- Reviewed PR #61 phone native audio controls after Neo's fix for `height: 0px`; required CI wiring and rebase, then mutation-tested the phone audio guard and merged after composed validation.
- Reviewed and merged PR #58 friendly status ladder after resolving conflicts while preserving #60 optional controls; Mouse and refreshed CI approved.
- Reviewed and merged PR #62 viewport usability guard. Verified it skips explicit collapsed semantics and mutation-tested the original `height: 0` bug so `ux:control-guard` fails before passing after revert.

📌 Team update (2026-08-12T17:49:51.136-07:00): Board cleared after PRs #55-#62 and issues #53/#44/#42/#40/#54. Mandatory lesson: user-visible UI requires BOTH code/behavior review and Mouse screenshot review; green CI and correct DOM/data flow can still hide zero-height controls. Switch PR #62 now guards hidden/zero-size/offscreen interactive controls on phone, and mutation testing is expected for behavior guards. Merge P0/overlapping PRs first, then re-check mergeability and CI after every merge; prefer stable test ids/role queries over exact copy for guards.
