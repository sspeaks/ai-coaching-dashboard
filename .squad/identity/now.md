---
updated_at: 2026-08-12T17:49:51.136-07:00
focus_area: Board clear — v0.4.0 UX remediation complete, viewport guard now in CI
active_issues: []
---

# What We're Focused On

Board is clear: 0 open issues, 0 open PRs. Ralph's loop closed #53, #54 (P0), #44, #42, #40 and merged #55–#62. The long-standing local/origin `main` divergence (7f2fe04, 64638fd, e017a92) was verified redundant and finally resolved.

Combined-state health check on merged `main` (ee0771b) came back clean: timestamps remain adjacent to the renamed play controls, phone native audio controls visible post-tap (height 40 at both widths), optional review disclosure findable and openable, status ladder coherent alongside first-run guidance. `ux:control-guard` passed across 216 phone controls.

## Standing rules adopted this session

1. **Both review gates are mandatory for type:ux PRs.** Screenshots and code review are mirror-image blind spots. #45 shipped a hardcoded 42% playhead invisible to screenshots; #57 passed code review + 4 green CI checks + 40 tests and still shipped a live P0 (native `<audio controls>` at `height: 0px` on mobile). Do not merge user-visible UI until BOTH Mouse and Morpheus report.
2. **Individually-verified parts do not compose into a verified whole.** Merge the highest-priority PR first, then re-check every remaining PR's mergeability and CI. Pre-existing green is invalid after any merge that touches shared files.
3. **Prefer test ids / role queries over literal user-facing copy in assertions.** Copy renames otherwise make guards pass vacuously.
4. **Mutation-test any assertion that claims to protect behavior.** It caught real problems twice this session (#57 playhead, #62 guard).
5. **A guard must be proven to fail** before it is trusted. #62 was demonstrated failing on reintroduced `height: 0`, then passing across 212 controls.

## Health watch

`.squad/decisions.md` grew 22,808 → 43,786 bytes this session (32 inbox entries merged). Nothing was archive-eligible (all within 30 days). It is approaching the 51,200-byte gate that triggers 7-day archiving — next session should expect aggressive archiving, and it is worth asking whether every entry needed to be a decision rather than agent history.

## Housekeeping left for Seth

- Uncommitted `.squad/` state (agent histories, decisions.md, UX review artifacts); local `main` is 2 commits behind origin/main and cannot fast-forward until resolved.
- Stale worktrees predating this session: `acd-issue39`, `acd-pr56-review`, `.review-pr55`.
