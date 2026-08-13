# Project Context

- **Owner:** Seth Speaks
- **Project:** Web interface for processing and reviewing barbershop coaching recordings
- **Stack:** React 19 + Vite + TypeScript at `apps/web`; shared client in `packages/web-client`
- **Created:** 2026-08-12T14:25:08.524-07:00
- **Users:** Barbershop quartet singers, not software engineers. Pipeline jargon is a defect.

## Learnings

- Created to satisfy the Reviewer Rejection Protocol after Mouse's 2026-08-12 review returned 🔴 Illegible on the existing UI. Trinity is locked out of those fixes; I own the revisions.
- Screenshot harness: `cd apps/web && npm run ux:capture` → `.squad/files/ux-review/{date}/` at 390x844, 360x800, 1440x900.
- Mock mode needs no backend: `VITE_API_MODE=mock`, states pinned via `?mockState=` (empty, upload-progress, processing, failed, awaiting-review, complete).
- The two task-blocking defects from the first review: timestamp chips don't read as audio controls, and the failure state offers no recovery action.

📌 Team update (2026-08-12T14:25:08.524-07:00): Link owns remediation for Mouse UX findings #36-#44. #36 and #37 are p0 release blockers; fixes require fresh screenshots and Mouse re-review — decided by squad-coordinator
📌 Team update (2026-08-12T14:25:08.524-07:00): Morpheus triaged UX review issues #36-#44 with squad:link and type:ux labels; #43 also has type:bug — decided by Morpheus

📌 Team update (2026-08-12T17:49:51.136-07:00): Issue #44 first-run desktop guidance now uses the empty feedback detail space as a large start-here callout with a primary upload action and a three-step next-preview; validation included dynamic first-run/upload tests plus fresh UX screenshots at .squad/files/ux-review/2026-08-12-link-44/. — decided by Link
📌 Team update (2026-08-12T17:49:51.136-07:00): Issue #40 remediation replaced primary pipeline jargon with the singer-facing ladder Uploading → Listening to the recording → Writing coaching notes → Ready to read → Needs help. Added App tests covering real job-state mappings and closed technical details, and refreshed UX screenshots in `.squad/files/ux-review/2026-08-13/`. — decided by Link
