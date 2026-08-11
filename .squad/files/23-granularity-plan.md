# Plan: Remove the fixed "Top 5" cap and tune deduplication

## TL;DR for Seth

Right now the system extracts **all** the coaching points from a recording (there's no cap on that part), but then it squishes them into exactly 5 "themes" when building the overview you see. If the coach gave you 11 distinct things to work on, you only see 5 headlines — the rest get silently folded in or lost.

**Recommended fix:** Remove the hard cap and let the model return as many themes as the coaching warrants, while instructing it to merge only points that are genuinely the same correction (same thing, same reason, same person). Two mentions of "tune the third" at different spots stay separate unless they're clearly the same recurring problem being revisited. The system already has per-entry timestamps, so merged themes still link back to every audio moment — you'll always be able to tap and hear the source.

**Risk I'm most worried about:** Over-merging — silently combining two distinct coaching points into one headline so you never realize something was lost. The plan below makes merged sub-items visible in the UI so you can always expand and check.

---

## Where the cap lives today

| Layer | File | Line | What it does |
|-------|------|------|--------------|
| Config default | `services/evidence-api/evidence_api/config.py` | 61 | `summary_theme_count: int = 5` — the default passed to the gateway |
| Gateway request schema | `services/extraction-gateway/extraction_gateway/app.py` | 62 | `theme_count: int = 5` in `SummaryRequest` |
| Gateway prompt | `app.py` | 381 | `"Group the supplied ledger entries into at most {body.theme_count} themes"` |
| Gateway post-processing | `app.py` | 446 | `themes = themes[: body.theme_count]` — hard slice after model returns |
| Worker caller | `services/evidence-worker/evidence_worker/worker.py` | 512 | passes `theme_count=self.settings.summary_theme_count` |

**No UI truncation exists** — the web component (`SessionOverviewPanel.tsx:126`) renders all themes it receives.

**Extraction (ledger entries) is uncapped.** The gateway already extracts every coaching point via overlapping windows and deduplicates across window boundaries using `(topic, segment_ids)` identity. The gold fixture has 11 entries, proving more than 5 are expected. The issue is purely the **summary/theme layer** that groups entries into headlines.

## How items are generated today

1. Audio → Speakr → transcript with timestamped segments.
2. Extraction gateway receives transcript windows, prompts the model for per-segment ledger entries (no count cap), deduplicates window-boundary repeats via `_entry_identity()` (topic + segment IDs).
3. Ledger entries are persisted — each has `evidence` with segment IDs and timestamps.
4. **Summary step:** all entries are sent to the gateway's `/summarize` endpoint, which prompts the model to group them into ≤ `theme_count` themes. Each theme cites `ledger_entry_ids`, and the evidence API derives `moments` (timestamps) from the cited entries.

**Existing dedup:** Only at extraction-window boundaries (same topic + same segments = duplicate). No semantic dedup exists within a single window or across the summary layer.

---

## Approaches considered

### A. Prompt-only: remove the cap, instruct the model to self-cluster

**How:** Change the summary prompt from "at most N themes" to "as many themes as there are genuinely distinct coaching points." Add explicit instructions: merge only when the same correction targets the same person for the same reason; when in doubt, keep them separate.

- **Pros:** Simplest change (~20 LOC). No new infra. Latency unchanged.
- **Cons:** Model compliance is non-deterministic; may still over-merge or under-merge without feedback. No eval gate today that catches wrong theme count.
- **Cost:** Zero incremental.

### B. Two-pass: extract freely, then a consolidation pass

**How:** After extraction, run a second model call that takes all ledger entries and returns a clustering (which entries are "the same coaching point revisited"). Then build themes from clusters.

- **Pros:** Separation of concerns (extract vs. consolidate). Consolidation prompt can be very targeted.
- **Cons:** Extra model call per session (adds ~5–15s latency, ~$0.01–0.03 for a typical session). More complex to test and maintain.
- **Cost:** Moderate — one additional GPT-4o call on a few KB of ledger text.

### C. Embedding-based post-processing

**How:** Embed each entry's `topic + exact_feedback`, cluster with a similarity threshold, one theme per cluster.

- **Pros:** Deterministic once the threshold is set. No model call.
- **Cons:** Requires an embedding model. Threshold tuning is fragile — semantic similarity between "tune the third in bar 12" and "tune the third in bar 40" is high, but they may be distinct corrections. Loses the model's understanding of coaching intent.
- **Cost:** Embedding call (~$0.0001 per entry) but adds a new dependency.

### D. Schema change: themes as groups with visible sub-items

**How:** Keep themes as groups of entries, but the UI renders each entry within a theme as a visible sub-item (with its own timestamp button). If the model over-merges, the user can see all the individual coaching moments inside a theme and notice if something doesn't belong.

- **Pros:** Makes over-merging recoverable rather than silent. Aligns with the existing `ledger_entry_ids` + `moments` schema — mostly a UI change.
- **Cons:** Doesn't solve the clustering accuracy problem by itself — needs pairing with A or B.

---

## Recommendation: A + D (Prompt-only removal of cap + visible sub-items in UI)

### Why

1. The extraction layer already does the hard work and is uncapped. The gold fixture proves 11 entries from one session. The "cap of 5" only constrains the grouping/summary view.
2. Removing the hardcoded `theme_count` and telling the model "return as many distinct themes as the coaching warrants" is the minimal correct fix. The model already sees all entries and their evidence — it has enough context to decide what's distinct.
3. Making sub-items visible (Approach D) is the safety net: if the model merges two points that shouldn't be merged, the user sees both moments listed under the theme and can mentally separate them. This makes over-merging **visible and recoverable** instead of silent.
4. A two-pass approach (B) is overkill for the current data size (5–15 items) and adds latency/cost without clear benefit until we see the prompt-only approach fail on real sessions.

### Concrete changes

| Area | Change |
|------|--------|
| `evidence-api/config.py:61` | Remove `summary_theme_count` default of 5; replace with a high soft maximum (e.g. 25) that exists only as a sanity guard, not a target |
| `extraction-gateway/app.py:62` | Change `theme_count` default from 5 → optional, default None (no cap) |
| `extraction-gateway/app.py:381` | Rewrite prompt: "Return one theme per genuinely distinct coaching point. Merge entries only when they address the same technique for the same singer for the same reason. When two mentions of the same correction appear at different times, include them in one theme with all their moments. Do not artificially limit the count." |
| `extraction-gateway/app.py:446` | Remove the `themes = themes[: body.theme_count]` hard slice (or make it conditional on a max guard) |
| `worker.py:512` | Stop passing a fixed `theme_count`; or pass the sanity-max |
| `SessionOverviewPanel.tsx` | Under each theme, render the individual moments as expandable sub-items showing the entry's `exact_feedback` or `topic` + timestamp button. Already partially there via `theme.moments`. |
| Contracts (`SummaryThemeCreate`) | No schema break needed — `themes: list[SummaryThemeCreate]` already has no max length |

### How to evaluate

1. **Extend the gold fixture:** Add a `gold-summary.json` alongside `gold-ledger.json` for `quartet-coaching-01` that declares expected theme count (should be ~7–8 for 11 entries based on content) and known merge pairs (e.g. entries i01+i02 both address "bass onset" → one theme). The `deterministic-evaluation` CI job already scores the ledger; extend `eval/score.py` to also score summary theme coverage:
   - **Theme recall:** every gold entry appears in at least one predicted theme.
   - **No orphan entries:** no entry assigned to zero themes.
   - **Merge accuracy:** known merge pairs share a theme; known distinct pairs do not.
2. **Live calibration:** Process 3–5 real coaching recordings (which Seth has) and manually verify item counts are in the 5–15 range he expects. This is a one-time human check, not CI.
3. **Regression gate:** The existing scorer already ensures `labelled intervention recall >= 90%` and `substantive entries with evidence = 100%`. Those still protect against under-extraction. A new "theme coverage" gate protects against silent over-merging at the summary layer.

### Failure mode and mitigation

| Failure | Impact | Mitigation |
|---------|--------|------------|
| Model over-merges (combines distinct points) | User misses a coaching correction | Sub-items are visible → user can see all moments. Eval gold fixture catches it in CI. Prompt explicitly says "when in doubt, keep separate." |
| Model under-merges (too many themes) | List is long but complete — low severity | Acceptable per user's own words ("I'd expect 5–15"). A sanity max of 25 logs a warning. |
| Model returns 0 themes | Existing error handling already covers this (502 if empty) | No change needed |

### Migration

- Sessions already processed have their summary stored. They have ≤5 themes.
- **No destructive migration needed.** We can offer a "re-summarize" button (already planned in the UI) that re-runs the summary with the new prompt. Old summaries remain valid — they're just less complete.
- The ledger entries are already uncapped and persisted. Only the theme layer is affected.

### Source-grounding preserved

- Every `SummaryThemeCreate` must have `ledger_entry_ids: list[str]` (min_length=1).
- The evidence API derives `moments` (start_ms/end_ms) from cited entries' evidence.
- A merged theme with entries from different timestamps will have multiple moments — exactly what we want ("Hear the 3 source moments").
- The prompt already says "Use only the supplied entries: every id you cite must be one you were given."

### Cost / latency

- **Zero additional model calls.** The summary is already one call; we're just changing what we ask for.
- Token output may increase slightly (more themes = more text), but for 5–15 themes the difference is negligible (~200 extra tokens, <$0.001).

---

## Open questions for Seth

1. Is a "re-summarize" button for old sessions acceptable, or do you want automatic re-processing of existing sessions?
2. For the UI sub-items: would you prefer them always visible, or collapsed under an "expand" control per theme?
3. Any real recordings you'd share as eval fixtures (anonymized or not) to calibrate beyond the synthetic one?
