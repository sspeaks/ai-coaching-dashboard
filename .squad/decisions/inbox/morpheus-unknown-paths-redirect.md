# Decision: Unknown paths redirect to feedback instead of showing 404

**By:** Morpheus
**Date:** 2026-08-11
**Issue:** #28

## Decision

Unknown/unmatched paths in the SPA router redirect to the feedback page (`/`) rather than displaying a "page not found" error screen.

## Rationale

- The app has exactly 3 user-facing routes (`/`, `/upload`, `/manage`). A dead-end 404 screen provides no value to non-technical quartet members.
- A real user's first impression was a confusing error — unacceptable for this audience.
- The "This page does not exist" page had a manual escape hatch (a button), but first-time users shouldn't need to figure out navigation from an error state.
- Risk of masking bugs is minimal: there are no deep-linkable session URLs, no user-generated paths, and only 3 routes to maintain. If a future route is added and misconfigured, the symptom would be "lands on feedback instead of new page" which is immediately obvious during development.

## Trade-off acknowledged

A catch-all redirect hides genuine 404s. For a developer-facing app this would be wrong. For a 3-route app used by singers, the UX benefit outweighs the debugging cost.
