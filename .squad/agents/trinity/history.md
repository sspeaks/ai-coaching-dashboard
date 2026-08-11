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
