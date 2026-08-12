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
