# Decision: Silent content truncation must always log

**By:** Morpheus
**Date:** 2026-08-11
**Issue:** #23

## Standing rule

Any code path that drops, truncates, or omits user-facing coaching content (themes, ledger entries, moments) MUST:

1. **Log a warning** at the point of truncation with the count of items dropped and the session ID.
2. **Where feasible, surface the loss** rather than silently discarding — e.g. add singleton fallback themes for orphaned entries rather than letting them vanish.

## Rationale

Silent truncation has appeared three times in this codebase:
- `themes[:5]` — original hard cap, invisible to users (issue #23)
- `themes[:body.theme_count]` with `theme_count=25` — dead-code warning, same class of bug relocated to a higher number
- Unclaimed pre_group entry IDs — logged as "uncovered" but no user-visible fallback

Each instance caused coaching feedback to disappear without the user knowing. For non-technical quartet members who cannot inspect logs or understand why a coaching point vanished, this is unacceptable.

## Implementation pattern

```python
# WRONG: silent truncation
themes = themes[:limit]

# RIGHT: log when truncation fires
if len(themes) > limit:
    logger.warning("truncating %s themes to %s session=%s", len(themes), limit, session_id)
    themes = themes[:limit]

# BEST: fallback for orphaned content
for unclaimed_id in orphaned_ids:
    themes.append(make_singleton_fallback(unclaimed_id))
```
