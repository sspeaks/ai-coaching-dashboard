## UX Review — PR #60 optional note review controls — 2026-08-12T17:49:51.136-07:00
Viewports: 390x844, 360x800, 1440x900
Verdict: 🟢 APPROVE

I formed this verdict from my own rendered screenshots in this directory, not from Link's committed capture. I read issue #42, PR #60, and original Mouse finding #7 first, then judged the visible UI from pixels.

### Original finding checked

Finding #7 from `.squad/files/ux-review/2026-08-12/REVIEW.md`: repeated “Looks right” / “Needs correction” radio controls and Save buttons were small and distracted from reading. Suggested fix: clarify optional vs required, make controls larger if needed, and avoid forcing review UI into the main reading path.

### Task walkthrough

1. Read coaching note without being interrupted by review controls → ✅ Obvious. The main note now shows coaching text, “Why might this be wrong?”, and source moments before the review UI.
2. Notice review controls still exist → ✅ Obvious. The collapsed row says “Optional: check this note” with a disclosure arrow and explanatory copy.
3. Understand review is optional → ✅ Obvious. The visible word “Optional” and “Open this only if you want…” copy make this non-required.
4. Open the controls on phone → ✅ Pass. At 390x844 and 360x800, expanded choices are large, full-width cards; Save is visible lower in the disclosure/full-page captures.
5. Open/close several notes → ✅ Pass from pixels. First and second disclosures both render content when opened; reclosing the second returns it to the compact optional row. I saw no empty panel, unexpected collapse, or obvious state-loss symptom.

### Evidence

Collapsed/default state:
- `phone-390x844/06-feedback-awaiting-review.png`
- `narrow-phone-360x800/06-feedback-awaiting-review.png`
- `desktop-1440x900/06-feedback-awaiting-review.png`
- `phone-390x844/08-note-review-disclosure-collapsed-closeup.png`

Opened/repeated states:
- `phone-390x844/09-note-review-disclosure-open-first.png`
- `phone-390x844/12-note-review-disclosure-open-second.png`
- `phone-390x844/13-note-review-two-disclosures-open-fullpage.png`
- `phone-390x844/14-note-review-second-reclosed.png`
- `narrow-phone-360x800/09-note-review-disclosure-open-first.png`
- `narrow-phone-360x800/12-note-review-disclosure-open-second.png`
- `desktop-1440x900/09-note-review-disclosure-open-first.png`
- `desktop-1440x900/13-note-review-two-disclosures-open-fullpage.png`

### Acceptance criteria check

| Criterion | Verdict | Screenshot evidence | Notes |
|---|---|---|---|
| UI makes clear whether reviewing each note is optional or required | ✅ Pass | `phone-390x844/08-note-review-disclosure-collapsed-closeup.png` | “Optional: check this note” is explicit. |
| If optional, controls do not interrupt main coaching-reading path | ✅ Pass | `phone-390x844/06-feedback-awaiting-review.png`, `desktop-1440x900/06-feedback-awaiting-review.png` | Controls are collapsed and placed after coaching text/source moments. |
| Collapsed disclosure is still findable | ✅ Pass | `phone-390x844/08-note-review-disclosure-collapsed-closeup.png` | The row is visible, labeled, and has a disclosure arrow. |
| Opened phone controls are tappable and do not overflow | ✅ Pass | `phone-390x844/09-note-review-disclosure-open-first.png`, `narrow-phone-360x800/09-note-review-disclosure-open-first.png` | Choices are comfortably large; no horizontal overflow or unmarked truncation visible. |
| Opening one disclosure does not show the #48-style missing-target bug | ✅ Pass from pixels | `phone-390x844/13-note-review-two-disclosures-open-fullpage.png`, `phone-390x844/14-note-review-second-reclosed.png` | Expanded content appears; siblings remain present; no empty/vanishing disclosure seen. |
| Cross-stream wording does not contradict #40/#59 | ⚠️ Non-blocking watch | `phone-390x844/09-note-review-disclosure-open-first.png` | Main visible review copy is friendly. The expanded helper still says “transcript editor” / “transcript updates”; this is jargon but hidden in optional review details and may be covered by #40. |

### Findings

No blocking UX findings from screenshots. The fix solves the central risk: the review feature is quieter but still visibly findable, and opening it produces reachable controls rather than an empty or hidden area.

Non-blocking consistency watch: the opened disclosure includes “transcript editor” and “transcript updates” language. That does not block this PR because it is optional secondary copy, but Morpheus should reconcile it with PR #58 / issue #40's friendly-status-language pass.

### What screenshots cannot verify

Morpheus/code review owns these non-pixel questions. From screenshots alone I cannot verify:

- keyboard operability of the disclosure, radio choices, textarea, or Save action;
- focus management after opening/closing disclosures;
- screen-reader labeling, fieldset legend, and described-by relationships;
- whether expanded disclosure content stays mounted in the DOM across route changes, playback actions, refreshes, or async updates;
- whether entered text/radio state persists after opening another note, playing a source moment, saving, or failed save;
- whether the Save action sends the correct note review data.
