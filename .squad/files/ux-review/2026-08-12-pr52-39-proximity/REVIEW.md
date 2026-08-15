## UX Pixel Gate — PR #52 / issue #39 — 2026-08-12
Viewports: 390x844, 360x800, 1440x900
Verdict: APPROVE
Evidence: `.squad/files/ux-review/2026-08-12-pr52-39-proximity/`

### Capture path
`npm run ux:capture` under `nix develop` still failed on the failed-state wait text (`We could not finish this recording.`). I used the fallback Nix/Playwright path for all 21 standard full-page states, waiting on structure instead of that stale literal copy. I also captured 8 viewport-only scrolled phone shots (`08-complete-scroll-*`) to judge sticky source recording behavior.

### Grounded before-state comparison
The original review at `.squad/files/ux-review/2026-08-12/REVIEW.md` found the source recording/audio player effectively detached from timestamp moments: the player lived below the notes, so a phone user had to scroll away from the advice to find the audio control and could not see cause/effect.

PR #52 materially changes that pixel relationship. In the new 360 and 390 phone captures, each note's `SOURCE MOMENTS` area contains always-visible, large play controls directly inside the note. The sticky `SOURCE RECORDING` panel remains visible at the top while scrolling through note 1, note 2, note 3, and the bottom of the page. The user no longer has to leave the advice card to find the play action.

### Findings
| Area | Judgment |
|---|---|
| Scroll distance between advice and audio | Meaningfully reduced. The play controls are now inline with the note's source moments; the sticky source panel stays visible during phone scrolling. |
| Phone sticky comfort | Acceptable at 390x844 and 360x800. It uses about 91px at the top, does not cover the inline play buttons in the scrolled captures, and does not trap the review form or bottom content. |
| Always-visible buttons | Clear tradeoff, but acceptable. They add height, especially at 360px, but read unmistakably as controls: blue bordered buttons, play icon, action verb, timestamp, and context text. |
| 360x800 clipping/overflow | No horizontal overflow or clipped controls found in the reviewed states. Buttons stack cleanly; the sticky panel remains within the viewport. |
| Regression checks | #50 upload consent/name guidance remains readable; #46 failed recovery remains actionable; #48 mobile feedback affordance remains visible; #45 timestamp play affordance remains obvious; #51 takeaway still precedes review/marking controls. |

### Could not verify from pixels
- Real audio playback, currentTime changes, and whether the native audio timeline advances correctly.
- Screen reader announcements / keyboard order.
- Live backend states outside the deterministic mock states.
