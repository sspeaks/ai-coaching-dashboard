# Project Context

- **Owner:** Seth Speaks
- **Project:** AI coaching dashboard for barbershop quartet recordings
- **Stack:** To be selected after build-vs-buy evaluation; local-first web workflow, audio/AI processing, and a NixOS module
- **Created:** 2026-08-06T18:29:43.244-07:00
- **Research:** `my-barbershop-quartet-records-coaching-sessions-as.md`

## Learnings

- The first decision is whether an existing product can satisfy upload, processing, grounded coach notes, critical timestamps, and NixOS-friendly operation.
📌 Team update (2026-08-10T14:08:35-07:00): Authentik-branded sign-in 500s before oauth2-proxy callback should be investigated first in Authentik server/worker logs, not the dashboard backend — decided by Morpheus

## 2026-08-10 — PR #19 contrast revision
- Took over Trinity's rejected feedback-first polish revision under reviewer protocol and fixed the dark-theme skip-link contrast by adding/using the `--on-brand` token on `--brand`.
- Verified the skip link is the first tab stop and moves focus to `<main>`; added regression coverage for that behavior.
## 2026-08-10 — Issue #8 sign-out and username
- Fixed dashboard sign-out to land on `/signed-out`, configure oauth2-proxy backend logout against the OIDC end-session endpoint, and document the required Authentik post-logout redirect.
- Added `/api/me` so the frontend can display the preferred username from oauth2-proxy headers, falling back to the email local part when no preferred username is present.
