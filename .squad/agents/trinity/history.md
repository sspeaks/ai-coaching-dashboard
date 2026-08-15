# Project Context

- **Owner:** Seth Speaks
- **Project:** Web interface for processing and reviewing barbershop coaching recordings
- **Stack:** Website stack to follow architecture decision; backend API and timestamp-addressable media
- **Created:** 2026-08-06T18:29:43.244-07:00
- **Research:** `my-barbershop-quartet-records-coaching-sessions-as.md`

## Learnings

- The core UX is upload, processing status, structured coach notes, verification state, and one-click return to critical audio timestamps.
- 2026-08-10: Reworked issue #3 UI around a singer's three jobs: sign in, upload one audio recording with clear progress, and read summarized timestamp-linked coaching feedback. Moved transcript refresh, cancellation, deletion, review confidence, and full-note detail behind calmer options so the landing path avoids pipeline jargon while preserving source links and exact-quote cautions.

## 2026-08-10T14:36-07:00 — Issue #7 upload consent disclosure

- Investigated the actual upload pipeline before writing copy: browser upload stores source media under `EVIDENCE_MEDIA_ROOT`; the worker sends audio to configured Speakr for transcription; optional `http_json` extraction sends transcript/ledger text through the extraction gateway to an OpenAI-compatible endpoint; deployed retention has no automatic original-media deletion.
- Added an accessible upload-time consent prompt and expandable plain-language disclosure in `UploadPanel`, with coverage in the web app test.
- Verified `cd apps/web && npm run typecheck && npm test && npm run build` passes.

## 2026-08-10T14:45-07:00 — PR #9 reviewer revision

- Re-checked Speakr deployment docs and Nix module: documented `speakr.env` uses OpenAI transcription variables by default, while `ASR_BASE_URL` can point Speakr at a self-hosted ASR service per deployment.
- Revised upload copy so external transcription processing is always visible, and expanded details now mention transcript/note text sent to AI extraction plus deletion limits for downstream providers.
- Re-verified `cd apps/web && npm run typecheck && npm test && npm run build` passes.
📌 Team update (2026-08-10T14:08:35-07:00): Upload pipeline is NOT local-only: audio goes to Speakr and may go onward to Speakr's configured ASR provider; transcript, ledger, and note text may go to an OpenAI-compatible extraction/summary gateway when configured — decided by Trinity and Fact Checker

## 2026-08-10T15:06-07:00 — Issue #10 feedback-first navigation

- Split the web UI into feedback-first home (`/`), upload (`/upload`), and management (`/manage`) SPA routes so summaries and timestamp links are the landing experience.
- Moved upload off the front page while preserving the Rai/Fact-Checker-approved consent disclosure copy unchanged inside the upload flow.
- Kept destructive recording deletion reachable on the management page and hid recording controls from the feedback reading surface.
- Verified `cd apps/web && npm run typecheck`, `npm test`, and `npm run build` pass.

## 2026-08-10T15:42-07:00 — Issues #15/#16/#17/#18 feedback-first polish

- Removed upload calls-to-action from the feedback page; upload remains reachable only through main navigation and management.
- Auto-opened the newest session on the feedback page so landing-to-summary is zero clicks when recordings exist, while the session list keeps other recordings one click away.
- Added a dark-only tokenized theme with checked contrast pairs for normal, muted, status, alert, button, consent disclosure, and timestamp-link colors.
- Added a plain-language catch-all page for unknown URLs with focus on main content and a direct button back to feedback.
- Verified `cd apps/web && npm run typecheck`, `npm test`, and `npm run build` pass.

## 2026-08-10T23:30-07:00 — Issues #20/#21 theme retheme + feedback declutter

- Moved dark theme from saturated green (--brand: #7bd8a8) to GitHub-inspired slate/blue palette (--brand: #388bfd, backgrounds #0d1117–#21262d). Changed --on-brand to #000000 (6.28:1 on #388bfd).
- Replaced every hardcoded green hex literal in styles.css with tokens or new neutral values. No color literals added to TSX files.
- Removed the welcome-panel hero banner from FeedbackPage — it was a ~1158×170 wide strip that added no information for a returning singer.
- Removed the "Step 2" eyebrow from SessionOverviewPanel — pipeline labels belong in the machine, not the UI.
- Suppressed the "Ready" status callout: if content is ready, show it. Processing and failed callouts retained.
- Demoted audio player from a two-column mid-page hero to a compact flex strip below the coaching notes. The seek function is unaffected (ref is attached to the DOM element regardless of position).
- Updated two test assertions to match the removed banner text; all 22 tests pass. Typecheck and build both clean.
- Mobile: audio-section goes flex-direction:column at ≤640px; tap targets verified ≥44px.

## 2026-08-11T00:30:00Z — Issue #24 evidence-link timestamp caption contrast

- Fixed `.evidence-link span:last-child` regression: `--muted` (#8b949e) on `--brand-soft` (#1f3349) = 4.19:1 (FAIL). Changed to `color: var(--ink)` = 10.92:1 (PASS).
- Full `--muted` survey across all elevated surfaces: only `--brand-soft` fails. `--surface` (5.62:1), `--surface-strong` (5.26:1), `--surface-muted` (4.95:1), `--attention-soft` (5.03:1), `--danger-soft` (5.64:1), `--success-soft` (5.41:1), `--info-soft` (5.25:1) all pass.
- The fix is surgical: token unchanged, only the pairing on `--brand-soft` repaired.
- Noted: 0.72rem caption is load-bearing per Rai (source-grounding). Proposed increasing to 0.8rem in PR — not unilaterally applied.
- All 22 tests pass. Typecheck and build clean.

## 2026-08-11T00:30:00Z — Issue #26 evidence-link caption font size

- Shipped `font-size: 0.8rem` on `.evidence-link span:last-child` (was 0.72rem, ≈11.5px → 12.8px).
- Proposal from #25 decision inbox was independently endorsed by both Rai and Switch before filing as issue #26.
- 375px layout verified: caption uses `grid-column: 1 / -1` (full button width, no horizontal growth), button width driven by timestamp/role row — font bump adds ~1.3px height only. Flex-wrap container handles multi-button layout cleanly. Touch targets unaffected (still > 44px).
- Contrast unchanged: `--ink` on `--brand-soft` = 10.92:1. Color not touched.
- All 22 tests pass. Typecheck and build clean.

## 2026-08-11T01:20:00Z — Rounds 11-18 Summary & Team Decision Codification

- Issues #20/#21 batched dark theme + declutter shipped via PR #22, caught contrast regression by Rai (7.30:1 → 4.19:1 on consent detail). Morpheus fix: `--muted` → `--ink` (10.92:1).
- Issues #24/#26 evidence-link contrast and caption font shipped in rounds 14–15.
- Contrast pairing rule now codified: `--muted` unsafe on elevated blue surfaces; fix the *pairing*, never retune the token globally. Verified safe values elsewhere (4.95:1, 5.62:1) would be invalidated if `--muted` itself changed.
- Product constraint reaffirmed: "Simplicity is #1 priority." Feedback page decluttered twice by user request (rounds #15, #21). Do not reintroduce visual density.
- Theme token discipline: all semantic colors behind tokens in styles.css `:root`, never hardcoded in TSX. Non-token hex only acceptable for decorative gradients and border helpers with no semantic meaning.

📌 Team update (2026-08-10T14:08:35-07:00): Upload pipeline is NOT local-only: audio goes to Speakr and may go onward to Speakr's configured ASR provider; transcript, ledger, and note text may go to an OpenAI-compatible extraction/summary gateway when configured — decided by Trinity and Fact Checker
📌 Team update (2026-08-11T01:20:00Z): Contrast pairing rule: `--muted` must NOT sit on elevated blue surfaces (e.g., `--brand-soft`) for consent, status, error text. Fix the *pairing*, never retune the token globally — verified values elsewhere (4.95:1, 5.62:1) would be invalidated. Applies to all future theme changes — decided by Morpheus
📌 Team update (2026-08-11T01:20:00Z): Product constraint binding team-wide: "Simplicity is #1 priority." Feedback page decluttered twice by user request. Do not reintroduce visual density in future UI changes — decided by sspeaks (user), implemented by Trinity
## 2026-08-11T01:30:00Z — Issue #31 (PR #33 fix agent) consolidation truncation coverage

- Named fix agent by Neo. Added `test_consolidation_singleton_truncates_long_topic` for `_coerce_consolidation`'s singleton truncation path (was zero-covered; `_coerce_summary`'s equivalent had a test but not consolidation's).
- Asserts on `caplog` log record ("truncated ungrouped entry topic" + eid) in addition to the truncated output — per Neo's requirement: an untested log line has no evidence it executes.
- Applied `[:197] + "…"` instead of bare `[:200]` in both truncation paths (Rai + Neo prescription): readers can see text is incomplete rather than guessing whether the sentence ended naturally.
- Fixed `summary=entry.topic` (full, untruncated topic) in `_coerce_summary` fallback; `SummaryThemeCreate.summary` accepts 4,000 chars and `entry.topic` is max 300, so it always fits whole.
- Updated `test_fallback_theme_truncates_long_topic` to match new scheme (198 chars = 197 + "…") and added summary assertion.
- Eval count: 14 eval on this branch (correct baseline). Neo saw 21 because he ran in the shared main checkout while Switch's #32 working-tree files were present — same shared-checkout problem, not branch contamination. Switch's #32 adds 7 eval tests (14→21). My branch was never involved; the worktree isolation worked as intended.
- pytest: 95 passed (was 94). Web tests: 23 passed. nix rebuild clean.
- Worked in `/home/sspeaks/projects/acd-issue31` worktree per team protocol.

## 2026-08-11T02:05:00Z — Rounds 19-21: Board Clear Summary

**Round 21 — Fix PR #33 (Morpheus locked out):**
- Added caplog test for truncation guard.
- Established binding rule: Truncate user-facing text with `[:N-3] + "…"`, never bare slice.
- Coaching text is qualifier-dense; ellipsis signals continuation and prevents misleading truncated text.

**Team Decisions Binding All Agents:**
- Concurrent agents MUST use separate git worktrees. Isolated working trees prevent cross-agent file interference.
- Guards must be proven to fire via caplog; untested log lines have no evidence they execute.
- Schema-boundary mismatches are recurring bugs — validate receiving constraint vs. sending.
- Truncate user-facing text with `[:N-3] + "…"`, never bare slice — users depend on visual honesty.
- Eval fixtures must default to failure (full matrix) not permission (enumerated list).

## 2026-08-12T14:25-07:00 — Mock state pinning for screenshot UX review

- Reworked `createMockEvidenceApiClient()` to use fixed timestamps, deterministic synthetic IDs, and realistic-but-obviously-synthetic quartet coaching data.
- Added `mockState` URL pinning for first-run empty, active processing, failed, awaiting-review, complete/reviewed, and additional backend state aliases without auto-advancing during polling.
- Added a held upload-progress screenshot state on `/upload?mockState=upload-progress` so Mouse/Tank can capture a non-flickering progress UI.
- Added mock-client tests for empty, processing, and complete deterministic states.
- Verified `cd apps/web && npm run typecheck && npm test && npm run build` passes (26 web tests). Also started the Vite dev server in mock mode and browser-checked the required state URLs.

📌 Team update (2026-08-12T14:25:08.524-07:00): Mock UI states are now selected by deterministic mockState URLs so screenshot review is stable across runs — decided by Trinity
📌 Team update (2026-08-12T14:25:08.524-07:00): Trinity is locked out of UX remediation findings #36-#44 under Reviewer Rejection Protocol. This is not a quality judgment; it preserves independent revision after a screenshot-only rejection, so Link owns the fixes — decided by squad-coordinator

## 2026-08-12T17:49:51.136-07:00 — Issue #54 compact summary source playback

- Fixed the summary-level “Play source at mm:ss” control so activation stays in the button plus the sticky Source recording player instead of inserting a full inline NowPlayingCue under the summary moment.
- Stopped passing the full theme summary as the playback cue source label, preventing the large blue now-playing box from repeating the whole advice paragraph.
- Tightened summary source-control/mobile audio CSS: explicit 44px minimum tap height, bounded moment groups, smaller sticky source-player padding, and compact transparent section cue styling.
- Added summary-specific interaction tests for seek/play, compact post-click state, pause/end/error clearing, and repeated moment clicks without inline layout insertion.
- Verified `cd apps/web && npm run typecheck`, `npm test`, and `npm run build` pass.
📌 Team update (2026-08-12T14:57:07.018-07:00): Code review of PR #45 exposed screenshot review's dynamic blind spot: a static 42% mini playhead and uncleared now-playing state were invisible in stills. For UI interactions, require behavior tests in addition to pixel review; always verify branch scope against origin/main. — decided by Ralph/Morpheus review loop
📌 Team update (2026-08-12T17:49:51.136-07:00): Board cleared after PRs #55-#62 and issues #53/#44/#42/#40/#54. Mandatory lesson: user-visible UI requires BOTH code/behavior review and Mouse screenshot review; green CI and correct DOM/data flow can still hide zero-height controls. Switch PR #62 now guards hidden/zero-size/offscreen interactive controls on phone, and mutation testing is expected for behavior guards. Merge P0/overlapping PRs first, then re-check mergeability and CI after every merge; prefer stable test ids/role queries over exact copy for guards.
