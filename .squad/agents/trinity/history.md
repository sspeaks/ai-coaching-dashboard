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
