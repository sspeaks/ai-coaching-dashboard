# Project Context

- **Owner:** Seth Speaks
- **Project:** Web interface for processing and reviewing barbershop coaching recordings
- **Stack:** React 19 + Vite + TypeScript at `apps/web` (dev: `npm run dev`, preview: `npm run preview`); shared UI in `packages/web-client`
- **Created:** 2026-08-12T14:21:12.929-07:00
- **Research:** `my-barbershop-quartet-records-coaching-sessions-as.md`

## Learnings

- Core user goals to walk through on every review: sign in, upload one audio recording with visible progress, read summarized coaching feedback, and jump back to a critical timestamp.
- Screenshot tooling (Playwright or equivalent headless browser) is NOT yet installed in this repo as of 2026-08-12. First task is to get capture working against `apps/web` before any verdict is issued.
- Screenshots are saved under `.squad/files/ux-review/{date}/` as review evidence.

## 2026-08-12 — First screenshot-only UX review

Verdict: 🔴 Illegible.

Reviewed 21 rendered screenshots across 390x844, 360x800, and 1440x900. Upload and long-running status are mostly understandable, but two primary tasks fail from pixels alone: users cannot confidently jump from a timestamped coaching note back to the audio, and the failed-recording state does not give an actionable recovery path. Top defects: timestamp chips look like citations instead of play/jump controls; audio player is detached at the bottom of the long note list, especially on phone; error recovery says to wait for “the issue” without telling the singer what to do; detailed notes read like a QA/review console before they read like coaching feedback. Full report: `.squad/files/ux-review/2026-08-12/REVIEW.md`.

📌 Team update (2026-08-12T14:25:08.524-07:00): Mouse is now the screenshot-only UX Review Engineer. Verdicts are based on rendered screenshots only; source may not influence the comprehension verdict — decided by squad-coordinator
📌 Team update (2026-08-12T14:25:08.524-07:00): First UX review returned 🔴 Illegible with 9 findings; timestamp jumping and failed-recording recovery block primary singer tasks — decided by Mouse

📌 Team update (2026-08-12T14:57:07.018-07:00): Screenshot review remains essential for pixel-level comprehension, but PR #45 proved its blind spot: a hardcoded playhead can look correct in every still image while failing every real session. Pair screenshot verdicts with behavioral tests for dynamic interactions. — decided by Ralph/Morpheus review loop

## 2026-08-12T17:49:51.136-07:00 — PR #57 compact summary source playback review

Verdict: 🔴 REJECT. Captured 23 rendered screenshots for PR #57 at 390x844, 360x800, and 1440x900, including required post-tap states. The inactive summary source controls are compact/tappable and the active state no longer repeats the full theme summary, but phone post-tap screenshots do not show native audio controls; the “native audio controls scroll target” still renders only a compact source cue/progress line on phone. Report: `.squad/files/ux-review/2026-08-12-pr57-review/REVIEW.md`.

Structural blind spot explicitly recorded: screenshots can show labels and layout, but cannot prove the playhead is real, audio seeks correctly, or state clears on pause/end/error.

## 2026-08-12T17:49:51.136-07:00 — PR #59 first-run upload guidance review

Verdict: 🟢 APPROVE. Captured independent screenshots for PR #59 at 1440x900, 390x844, and 360x800. The first-run desktop view now uses the empty detail area for a prominent “Upload your first rehearsal recording” callout, primary “Upload a recording” button, and “What happens next” preview. Phone layouts stack cleanly with no visible horizontal overflow or unmarked truncation. Report: `.squad/files/ux-review/2026-08-12-pr59-review/REVIEW.md`.

Learning reinforced by Ralph/Seth feedback: keep UX verdicts strictly scoped to what pixels prove, and keep listing what screenshots cannot verify. PR #57 showed pixel review can catch visual control-access defects that green CI/code review miss, just as code review catches dynamic defects screenshots cannot prove.

## 2026-08-12T17:49:51.136-07:00 — PR #60 optional note review controls review

Verdict: 🟢 APPROVE. Captured independent screenshots for PR #60 at 1440x900, 390x844, and 360x800, including collapsed, opened, two-open, and reclosed note-review disclosure states. The controls no longer interrupt reading, the collapsed row remains findable as “Optional: check this note,” and opened phone controls are large with no visible overflow. Report: `.squad/files/ux-review/2026-08-12-pr60-review/REVIEW.md`.

Learning: when a fix hides previously distracting controls, explicitly verify both that the hidden control remains discoverable and that the opened state renders real, tappable content. Pixel review can flag missing/empty disclosure symptoms, but cannot prove keyboard/focus/ARIA or mounted-state behavior.

## 2026-08-12T17:49:51.136-07:00 — PR #61 phone native audio controls re-review

Verdict: 🟢 APPROVE. Captured independent screenshots for PR #61 at 1440x900, 390x844, and 360x800, including post-tap 1:14 and 2:12 states. Phone native audio controls are now visibly present at 40px height inside the source recording panel, compact source cues remain, and the mini playhead visibly differs between 1:14 (~25.87%) and 2:12 (~46.15%). Report: `.squad/files/ux-review/2026-08-12-pr61-review/REVIEW.md`.

Learning reinforced: when screenshots reveal a control is visually absent, list both possibilities—missing from DOM vs present but visually suppressed. PR #61 confirmed PR #57's invisible phone audio controls were present but zero-height in mobile layout.

## 2026-08-12T17:49:51.136-07:00 — PR #58 friendly recording status ladder review

Verdict: 🟢 APPROVE. Captured independent screenshots for PR #58 at 1440x900, 390x844, and 360x800, including Uploading, Listening to the recording, Writing coaching notes, Ready to read, and Needs help states plus opened Technical details. Primary labels are singer-friendly, backend statuses remain in optional detail, failure recovery is understandable, and 360px captures show no visible overflow or unmarked truncation. Report: `.squad/files/ux-review/2026-08-12-pr58-review/REVIEW.md`.

Learning: copy-heavy UX reviews must be judged as a sequence through the product, not as isolated attractive screenshots. For status ladders, independently capture every rung, especially failure, and verify technical details are demoted rather than silently removed.
📌 Team update (2026-08-12T17:49:51.136-07:00): Board cleared after PRs #55-#62 and issues #53/#44/#42/#40/#54. Mandatory lesson: user-visible UI requires BOTH code/behavior review and Mouse screenshot review; green CI and correct DOM/data flow can still hide zero-height controls. Switch PR #62 now guards hidden/zero-size/offscreen interactive controls on phone, and mutation testing is expected for behavior guards. Merge P0/overlapping PRs first, then re-check mergeability and CI after every merge; prefer stable test ids/role queries over exact copy for guards.

### 2026-08-12T17:49:51.136-07:00 — Main combined-state UX health check
- After PRs #57, #59, #58, #60, #61, and #62 merged, independently captured current `origin/main` at 390x844, 360x800, and 1440x900.
- Clean composed pixels held: source play controls still show adjacent timestamps, phone native audio controls remain visible post-tap, optional review disclosure stays findable/openable, and the friendly status ladder reads coherently beside first-run guidance.
- `ux:control-guard` passed on 216 phone controls; keep using post-tap combined captures because individual PR approvals do not prove composition.
