APPROVE — Mouse UX visual gate for PR #45 / issue #36.

Evidence: `.squad/files/ux-review/2026-08-12-pr45-mouse-final/`

Captured 390x844, 360x800, and 1440x900 across empty feedback, upload ready/progress, processing, failed recovery, awaiting review, reviewed complete, and reviewed complete with an activated timestamp / now-playing cue.

Direct answer on #36: yes, the timestamp chips now visually read as play controls. The blue button treatment, play icon, explicit “Play … at [time]” copy, and active “Now playing” state make the affordance unambiguous at a glance. The NowPlayingCue reads as status, is placed near both the source recording and requesting note, and does not clip on narrow phone.

Regression check: no visual regression observed for #50 upload privacy disclosure scannability/narrow-phone layout, #46 failed-recording recovery affordances, or #48 mobile read-feedback disclosure.

Not verified from pixels: real audio playback start, playhead synchronization to actual audio time, and clearing “Now playing” on pause/end/error. Those remain Switch/code-test ownership.
