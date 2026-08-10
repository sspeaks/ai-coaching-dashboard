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

## 2026-08-11 — PR #22 dual defect fix (reviewer rejection protocol)

Both Rai (🔴 blocking: consent disclosure contrast) and Switch (🧪 tap targets) rejected PR #22 and nominated me. Trinity is locked out.

**Defect 1 — disclosure contrast:**
- `.privacy-disclosure div` had `color: var(--muted)` on `var(--brand-soft)`. New GitHub-neutral palette made `--brand-soft` = #1f3349, so `--muted` (#8b949e) on it = 4.19:1 — below WCAG AA 4.5:1 for 0.9rem non-bold text.
- Fixed: changed to `color: var(--ink)` → 10.92:1. `UploadPanel.tsx` is byte-identical; rendering-only fix.
- Surveyed all four `brand-soft` surfaces. Found `--muted` also used on `.evidence-link span:last-child` (0.72rem timestamp captions, 4.19:1). Not consent/status/error — noted in PR comment; deferred to a dedicated a11y pass.
- Did NOT change the `--muted` token globally — Switch verified it passes on surface and surface-muted.

**Defect 2 — tap targets:**
- `.button min-height: 2.55rem` (40.8px) → `2.75rem` (44px). Resolves iOS/WCAG floor.
- `.button--compact` (35.2px, pre-existing icon-button affordance in session-list rows) — left unchanged. Raising it to 44px would negate its purpose and risk distorting dense-row layout. Documented reasoning explicitly in commit and PR comment.
- 375px viewport: height-only change, no width impact, no wrapping or overflow risk.

**Results:** 22/22 web tests ✅, typecheck ✅, build ✅ (229.70 kB JS, 15.63 kB CSS).

**Decision written:** `.squad/decisions/inbox/morpheus-muted-on-brand-soft-consent.md` — standing rule against using `--muted` on elevated surfaces for consent/status/error text. This is the second consecutive theme PR to produce a contrast regression; the rule should prevent a third.
