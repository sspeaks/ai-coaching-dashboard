# 2026-08-12T17-49-51.136-07-00 — Phone viewport controls must be geometrically usable

**By:** Switch

**What:** CI must include a phone-viewport geometry guard for visible interactive controls. DOM presence is insufficient: controls must have non-zero rendered dimensions, visible computed styles, reachable viewport geometry after scrolling, and a hit-testable point that is not fully clipped or covered.

**Why:** Issue #54/PR #57 proved that `<audio controls>` can exist in the DOM with correct playback data while mobile flex layout collapses the native control to `height: 0px`, leaving users unable to pause or scrub. This is the same quality family as mounted-but-unusable disclosures and static playheads: passing structural assertions can still fail the member task.

**Rule:** The guard skips only intentionally collapsed content with explicit semantics (`hidden`, `aria-hidden="true"`, `inert`, or non-summary contents of closed `<details>`). Disclosure triggers and other visible controls remain in scope. Future UI work that adds interactive surfaces at phone widths should either be reachable by this guard's mock states or add a mock state before relying on CI.
