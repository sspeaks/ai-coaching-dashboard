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

## 2026-08-11 — Issue #28 post-login 404 fix

- **Root cause:** Caddy standard directive ordering runs `try_files` (a rewrite) before `forward_auth` (which captures the original `{uri}`). When unauthenticated users request `/`, Caddy rewrites it to `/index.html` before forward_auth can capture the path. oauth2-proxy then redirects post-login to `/index.html` instead of the original `/`. Every login showed `GET "/oauth2/start?rd=https://streams.sspeaks.net/index.html"` regardless of device.
- **Fix:** Wrapped the frontend `staticRoot` handler in a `route {}` block to enforce the written order, so `forward_auth` runs before `try_files` and captures the original path correctly.
- **Defense in depth:** Added `/index.html` as a known SPA alias for feedback page (secondary safeguard even if Caddy ordering is wrong).
- **Catch-all preserved:** Unknown paths still land on the catch-all 404 page (from issue #17).
- **Nix tests:** `api-auth-contract`, `proxy-prefix-contract`, `external-tls-proxy`, `fresh-deploy` all built successfully.
- **Decision written:** `.squad/decisions/inbox/morpheus-unknown-paths-redirect.md` — Caddy `route {}` block rule. Any handler combining `try_files` with `forward_auth` must use `route {}` to preserve written order and prevent path rewriting from corrupting authentication redirects.

## 2026-08-11 — PR #30 extraction/item-cap fix (reviewer rejection protocol)

Neo authored the two-pass consolidation for issue #23 (item-cap redesign); Switch and Rai both requested changes. Neo is locked out; I'm nominated as fix agent.

**Switch's three blocking findings:**
1. Dead-code `theme_count=25` guard — removed by setting to `None` instead.
2. No degradation test for own-scorer attack vector (scorer returns ≤-5 for all entries) — added specific test case.
3. Own-scorer attacks 5 & 6 succeed — mitigated by singleton fallback theme for orphaned entries (addresses Rai's silent-truncation audit in parallel).

**Rai's yellow verdict (resolved):**
- `.coerce_summary` silently dropped unclaimed pre_group entry IDs without logging.
- **Fix:** Added logging at drop point and fallback theme creation for each unclaimed ID. Now every orphaned entry gets a singleton theme with "No assigned category" caption + the ID. Users see feedback is present; operators can log-grep the source and fix data flow.
- **Decision written:** `.squad/decisions/inbox/morpheus-silent-truncation-must-log.md` — this is the *third* appearance of silent-truncation (themes[:5], themes[:25], unclaimed IDs). Standing rule: any code path dropping content MUST log + attempt fallback. Future audit focus: silent truncation.

**Attack surface status (post-fix):**
- Attacks 1–4: Already prevented by contract validation.
- Attacks 5 & 6: Now fail (scorer edge case handled).
- Attacks B/C/D/F: Remain unresolved by design (acceptable residual risk, documented in PR).

**Results:** All 87 FastAPI tests ✅, Nix checks ✅, Switch approved on re-review, Rai approved with note on new 🟡 (fallback title truncation length — filed as #31, deferred to future round).

**Decisions written:** Caddy routing rule, Silent truncation ban. Both merged to `decisions.md` by Scribe after round 18.

📌 Team update (2026-08-10T14:08:35-07:00): Authentik-branded sign-in 500s before oauth2-proxy callback should be investigated first in Authentik server/worker logs, not the dashboard backend — decided by Morpheus
📌 Team update (2026-08-11T01:20:00Z): Caddy `route {}` rule: any handler combining `try_files` with `forward_auth` MUST wrap in `route {}` to enforce written order and prevent path rewriting from corrupting post-login redirects (issue #28). Standing rule team-wide — decided by Morpheus, verified by Switch
📌 Team update (2026-08-11T01:20:00Z): Silent truncation ban: any code path dropping user-facing content (themes, ledger, moments) MUST log + surface fallback. Defect appeared 4 times; now codified as binding rule (issue #23, #30). Applies to all future code changes — decided by Morpheus, Rai
📌 Team update (2026-08-11T01:20:00Z): Contrast pairing rule: `--muted` unsafe on elevated blue surfaces for consent/status/error text. Fix the *pairing*, never retune the token globally — verified values elsewhere (4.95:1, 5.62:1) would be invalidated (issue #22). Applies to all theme changes — decided by Morpheus, verified by Switch, Rai
