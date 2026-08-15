## UX Review — merged main combined-state health check — 2026-08-12T17:49:51.136-07:00
Viewports: 390x844, 360x800, 1440x900
Verdict: health check only — no PR approval/rejection

I checked current `origin/main` after the full batch merged. I used a clean worktree, ran `npm ci`, captured my own screenshots, and ran the phone usability guard. Evidence is in this directory.

### Capture scope

- Source checked: `origin/main` at `ee0771b test: add phone viewport usability guard (#62)`
- Commands run:
  - `npm ci`
  - `UX_CAPTURE_DATE=2026-08-12-main-combined nix develop --command bash -lc 'cd apps/web && npm run ux:capture && npm run ux:control-guard'`
- Result: 24 stock screenshots plus 12 extra interaction screenshots. `ux:control-guard` passed and checked 216 phone controls.

### Composition checks

| Check | Result | Evidence | Notes |
|---|---|---|---|
| #58 copy rename vs #54 P0 intent | ✅ Holds | `phone-390x844/08-feedback-source-playing.png`, `narrow-phone-360x800/08-feedback-source-playing.png`, `phone-390x844/09-source-playing-second-moment-2-12.png` | The play buttons now say “Play recording…” / “Play this moment,” but the timestamp remains immediately adjacent: `1:14`, `2:12`, and `3:31` are visible in the control text and active cue. |
| #61 phone native audio controls survived composition | ✅ Holds | `phone-390x844/08-feedback-source-playing.png`, `narrow-phone-360x800/08-feedback-source-playing.png`, `09-source-playing-second-moment-2-12.png` | Native play/pause/scrub controls are visible post-tap on both phone widths. Manifest metrics show audio height `40` on 390 and 360. |
| #57/#61 compactness preserved | ✅ Holds | `08-feedback-source-playing.png`, `09-source-playing-second-moment-2-12.png` | No return of the large duplicate summary blue box. The cue is brief and the recording controls stay near the notes. |
| #60 optional disclosure still behaves | ✅ Holds | `phone-390x844/11-note-review-disclosure-collapsed-closeup.png`, `phone-390x844/12-note-review-disclosure-open.png`, `narrow-phone-360x800/12-note-review-disclosure-open.png` | “Optional: check this note” is visible while collapsed, opens with content, and does not show empty/vanishing disclosure content. |
| Full status ladder reads coherently | ✅ Holds | `04-feedback-processing-transcribing.png`, `05-feedback-failed-error.png`, `06-feedback-awaiting-review.png`, plus upload captures | The visible sequence uses friendly user language. The shipped ready state reads as “Ready to read,” which is consistent with the approved #58 review and does not conflict with #59's first-run preview. |
| #59 first-run guidance still fits beside ladder | ✅ Holds | `01-feedback-empty-first-run.png`, `02-upload-ready-idle.png`, `03-upload-in-progress.png` | Upload guidance, “What happens next,” and navigation remain visible; no obvious cross-copy contradiction. |
| 360px overflow/truncation | ✅ Holds | `narrow-phone-360x800/*.png`, guard pass | Labels wrap rather than overflow. I did not see unmarked truncation in the reviewed states. |

### Findings by severity

- **High:** none from screenshots.
- **Medium:** none from screenshots.
- **Low / follow-up:** none requiring issue filing. The composed main state preserved the intended fixes from #58, #59, #60, and #61 in the captured flows.

### What screenshots cannot verify

Morpheus/code and automated behavior tests own these non-pixel questions. From screenshots alone I cannot verify:

- whether status labels are driven by real backend job state rather than hardcoded strings;
- whether the audio playhead and timestamp seeking update correctly during real playback;
- whether pause/end/error clears now-playing state in all browsers;
- whether keyboard operation, focus management, and screen-reader labels match the visible controls;
- whether every production error maps to “Needs help” with the right recovery action;
- whether real uploaded audio metadata changes layout outside the deterministic mock scenarios.

### Bottom line

Clean composed-state health check from pixels: no visible regressions found. The timestamp remains adjacent to source play controls, phone native audio controls are visible post-tap, optional review disclosures remain findable/openable, and the status ladder reads coherently with first-run guidance.
