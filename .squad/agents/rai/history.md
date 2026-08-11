# Project Context

- **Owner:** Seth Speaks
- **Project:** AI coaching dashboard for barbershop quartet recordings
- **Stack:** Web-facing evidence API, optional AI extraction, and a NixOS module
- **Created:** 2026-08-06T18:29:43.244-07:00
- **Research:** `my-barbershop-quartet-records-coaching-sessions-as.md`

## Learnings

- Accessibility is not a feature — it's part of the product. Every defect in contrast, touch target, or keyboard navigation breaks the experience for users who need it.
- The core evidence surface (timestamp buttons linking coaching feedback) is load-bearing for source-grounding. Users must see *where* coaching notes came from (audio timecode) to verify and act on feedback.
- Silent truncation is a defect class: any code that drops user-facing content without logging or fallback undermines non-technical users' ability to understand why feedback disappeared.

## 2026-08-10T14:08:35-07:00 — Fact-Checker Review: Upload Disclosure

- Verified Trinity's copy against implementation: audio stored under evidence media root, sent to Speakr, forwarded to configured ASR provider (OpenAI or self-hosted), transcript/ledger/note text sent to configured extraction gateway (OpenAI-compatible by default).
- Confirmed: retention is not automatic; deletion is hard-delete of dashboard rows + depends on Speakr provider success. Operators control backup/retention via manual tooling outside the app.
- Found material omissions in Trinity's disclosure: downstream ASR hop and ledger/note text export were not mentioned. Added both to final copy before upload consent panel shipped.
- Result: Upload disclosure now legally and ethically complete, visible at upload decision point.

## 2026-08-10T15:52-07:00 — RAI Review: PR #19 (Trinity's feedback-first polish)

- **Verdict:** REQUEST CHANGES — skip link keyboard visible on `var(--brand)` (#7bd8a8) shows white-text contrast of 1.72:1 against green. Fails WCAG AA (minimum 4.5:1 for normal text).
- Result: Morpheus nominated, fixed by adding/using `--on-brand` token. Re-review approved by Morpheus post-fix.

## 2026-08-10T16:53-07:00 — RAI Review: PR #22 (Trinity's GitHub-neutral theme + declutter)

- **Verdict:** 🔴 RED — blocking consent disclosure contrast loss. `.privacy-disclosure div` shows `color: var(--muted)` on new `var(--brand-soft)` (#1f3349) = 4.19:1. Fails WCAG AA 4.5:1 floor for 0.9rem text carrying legal consent terms.
- Secondary finding: `.evidence-link span:last-child` same pairing, same 4.19:1 failure — not consent/status/error, so deferred to a separate a11y pass.
- This is the second contrast regression in two consecutive theme PRs (#19 skip link at 1.72:1, #22 consent at 4.19:1). Standing rule needed.
- **Decision written:** `.squad/decisions/inbox/morpheus-muted-on-brand-soft-consent.md` (merged post-Morpheus fix).

## 2026-08-10T17:03-07:00 — RAI Review: PR #25 (Trinity's evidence-link fix)

- **Verdict:** ✅ APPROVED — `.evidence-link span:last-child` changed from `--muted` (#8b949e) to `--ink` on `--brand-soft` (#1f3349) = 10.92:1. WCAG AAA for 0.72rem caption text. Safe.
- Noted: Caption is load-bearing for source-grounding per evidence API design; users rely on timestamp button text to navigate and verify coaching. Legibility matters.
- Approved PR #25 (merged).

## 2026-08-11T00:30-07:00 — RAI Review: PR #27 (Trinity's caption font resize)

- **Verdict:** ✅ APPROVED — `.evidence-link span:last-child` `font-size: 0.8rem` (was 0.72rem). No contrast change, legibility improvement for 0.72rem ≈ 11.5px → 0.8rem ≈ 12.8px on mobile (375px viewport).
- Verified: touch targets unaffected (≥44px), layout stable (caption uses grid-column: 1 / -1 so width is button-driven).
- Approved PR #27 (merged).

## 2026-08-11T01:05-07:00 — RAI Review: PR #30 (Neo's two-pass consolidation for issue #23)

- **Verdict:** 🟡 YELLOW (defect found) — blocking defect: `.coerce_summary` silently drops unclaimed pre_group entry IDs. `themes[:body.theme_count]` only surfaces claimed items; unclaimed IDs are discarded without logging or fallback. This is silent truncation — third appearance (themes[:5], themes[:25] dead-code warnings, now unclaimed IDs).
- **Standing rule needed:** Any code path dropping user-facing content MUST log the drop and attempt fallback where feasible. Non-technical quartet members cannot debug why coaching feedback vanished; silent truncation is unacceptable.
- **Decision written:** `.squad/decisions/inbox/morpheus-silent-truncation-must-log.md` (merged post-Morpheus fix).
- Nominated Morpheus as fix agent (Neo locked out under Reviewer Rejection Protocol).

## 2026-08-11T01:15-07:00 — RAI Re-review: PR #30 after Morpheus fix

- **Morpheus fixed:** `.coerce_summary` now logs at drop point and creates singleton fallback themes for each unclaimed ID with "No assigned category" caption + ID. Orphaned entries are now visible to users; operators can trace the source.
- **Verdict:** 🟢 GREEN (resolved) — silent truncation defect closed.
- **New 🟡 discovered:** Fallback title generation can exceed 64-char safe range in edge cases where unclaimed entry ID is long. **Filed as #31** (title truncation safety) for future Morpheus round.
- Approved PR #30 on re-review.

## 2026-08-11T01:20:00Z — Rounds 11-18 Summary & Team Decision Codification

- Reviewed three theme/UI PRs across rounds 12–15 and caught two contrast regressions (#19, #22) before shipping.
- Identified silent truncation as a systemic defect class (three instances) and codified standing rule: any code dropping user-facing content must log + fallback.
- Key learnings: Second-order effects matter (token reuse in new contexts can break contrast), and silent drops undermine non-technical users' trust.

📌 Team update (2026-08-11T01:20:00Z): Silent truncation ban: any code path dropping user-facing content (themes, ledger, moments) MUST log + surface fallback. Defect appeared 4 times; now codified as binding rule. Applies to all future code changes — decided by Morpheus, Rai
📌 Team update (2026-08-11T01:20:00Z): Contrast pairing rule: `--muted` unsafe on elevated blue surfaces for consent/status/error text. Fix the *pairing*, never retune the token globally — verified values elsewhere (4.95:1, 5.62:1) would be invalidated. Applies to all theme changes — decided by Morpheus, verified by Rai
📌 Team update (2026-08-11T01:20:00Z): Evidence-link captions are load-bearing for source-grounding — users rely on timestamp button text to navigate and verify coaching. Legibility and contrast both matter for this affordance — decided by Rai

## 2026-08-11T02:05:00Z — Rounds 19-21: Board Clear Summary

**Round 19 — RAI Review PR #33 (Morpheus consolidation fix):**
- Approved PR #33.
- Advisory: `summary` field could carry full untruncated topic and be truncated at render time. Storage truncation correct here.

**Team Decisions Binding All Agents:**
- Concurrent agents MUST use separate git worktrees. Shared checkout caused cross-agent interference.
- Guards must be proven to fire via caplog; untested log lines have no evidence they execute.
- Schema-boundary mismatches are recurring defect class — validate receiving constraint vs. sending (lengths, enums, optionality).
- Truncate user-facing text with `[:N-3] + "…"`, never bare slice — prevents misleading truncation.
- Eval fixtures must default to failure (full matrix) not permission (enumerated list).
