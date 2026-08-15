# UX Pixel Gate — PR #51 / Issue #38 — 2026-08-12

Evidence: `.squad/files/ux-review/2026-08-12-pr51-38-hierarchy/`

Viewports: 390x844, 360x800, 1440x900
States captured: empty feedback, upload idle, upload in-progress, processing, failed recovery, awaiting-review notes, completed-review notes, timestamp-click attempt.

Verdict: APPROVE

## Hierarchy judgment

The coaching takeaway now leads visually. In both phone and desktop captures, each note opens with the note title followed immediately by a bordered, higher-contrast `Coaching takeaway` panel. The bold takeaway sentence is the first dense text block that pulls the eye. The review/warning material is lower, quieter, and grouped under `Why might this be wrong?`, so it no longer reads as the lead content.

Warnings remain adequately discoverable. They are still directly under the takeaway, visibly labeled, and expanded in the captured note state. The `Not checked`, `Checked`, and `Needs correction` badges remain visible without overpowering the coaching message.

## Regression check

- #50 upload privacy disclosure: no visible regression. The upload screen still shows the processing-path disclosure before the upload button on phone and desktop.
- #46 failed-recording recovery: no visible regression. The failed state still has a red error, specific recovery copy, and `Upload a different file` / `Check again` actions without clipping.
- #48 mobile read-feedback disclosure: no visible regression. The selected recording clearly says `Feedback open` and points users downward to the open notes.
- #45 timestamp/source-recording affordance: no static visual regression. Timestamp buttons and the source recording area remain visible and legible. Still screenshots did not prove audio playback behavior; Switch's code gate should own that dynamic assertion.

## Capture note

The documented `npm run ux:capture` command failed on the failed-recording wait text, so I used a Nix/Playwright fallback to capture the same mock states plus a timestamp-click attempt. Pixels, not source, formed this verdict.

## Pixel-only limits

I did not verify backend persistence, DOM ordering, media playback, mutation resistance, or whether clicking a timestamp actually seeks audio in a real browser session. Those belong to the code/behavior gate.
