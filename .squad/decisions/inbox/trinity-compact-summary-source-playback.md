### 2026-08-12T17:49:51.136-07:00: Summary source playback uses active buttons plus compact sticky player
**By:** Trinity
**What:** Summary-level source moments should not insert a full inline NowPlayingCue after activation. The tapped button becomes the local “Now playing source at mm:ss” confirmation, while the sticky Source recording player carries the native audio controls and compact progress cue. Full theme summaries are not passed into playback cue source labels.
**Why:** The #54 regression came from combining always-visible summary source controls with a full-size cue that repeated the advice text. Keeping the confirmation in the button avoids layout jumps under repeated taps, preserves proximity to the advice, and keeps pause/scrub controls immediately reachable on phone.
