# Squad Decisions

## Active Decisions

### 2026-08-10: Treat Authentik-branded login 500s as IdP incidents first
**By:** Morpheus
**What:** A branded `500 / Internal Server Error` shown during OIDC sign-in, before oauth2-proxy returns to `/oauth2/callback`, is owned by the Authentik/OIDC deployment path rather than the React dashboard or FastAPI backend. The first confirmation artifact must be Authentik server/worker logs for the failing username and provider slug.
**Why:** The repository topology routes unauthenticated browsers from Caddy to oauth2-proxy and then to Authentik. A public probe reached Authentik `/application/o/authorize/` with the expected callback and scopes; FastAPI only sees requests after oauth2-proxy has accepted the token and copied identity headers.

### 2026-08-07T10:32:42.057-07:00: Structured extraction uses a separate OpenAI gateway
**By:** Neo
**What:** Added an optional `extraction-gateway` FastAPI service that implements the existing `http_json` extraction contract, authenticates inbound bearer requests, calls OpenAI with JSON schema structured output, and validates returned ledger entries against `coaching_contracts` before returning them to the worker.
**Why:** Seth chose a separate gateway to keep a vendor boundary around transcript text. The worker can stay vendor-neutral while the gateway owns provider credentials, citation validation, and OpenAI-specific response handling.

### 2026-08-07T12:12:18.011-07:00: Gateway rejection counts remain contract-compatible
**By:** Neo
**What:** Added warning logs for model entry citation rejections and returned `model_entry_count` / `rejected_entry_count` top-level metadata while also copying those counts into surviving entries' `extraction_metadata`.
**Why:** The evidence API `http_json` client reads `payload["entries"]` and validates only each entry, so extra top-level keys are compatible while making silent drops observable for operators and future callers.

### 2026-08-10: Member-first UI hides workflow internals by default
**By:** Trinity
**What:** The web UI should present sign-in, recording upload/progress, and timestamp-linked coaching feedback as the primary path. Transcript refresh, cancellation, deletion, summary regeneration, confidence details, and the full note archive belong behind options or drill-down controls.
**Why:** Quartet members are non-technical users who need to know what to do next and where each coaching point came from, not the backend state machine or review pipeline. Evidence grounding stays visible through timestamp buttons and exact-quote copy, while operational controls remain available without cluttering the main experience.

### 2026-08-10T14:08:35-07:00: Upload disclosure must include full external processing path (consolidated)
**By:** Trinity, Fact Checker
**What:** Uploaded audio is saved under the evidence API media root, retained until explicit/admin deletion or manual operator retention tooling, sent to configured Speakr for transcription, and may then be forwarded by Speakr to its configured ASR/transcription provider. Optional structured note extraction and AI summaries may send transcript, ledger, and note text to the configured HTTP JSON extraction gateway, whose default implementation calls an OpenAI-compatible chat completions endpoint. Confirmed deletion hard-deletes dashboard media/session rows and depends on Speakr deletion succeeding when remote media exists.
**Why:** User-facing upload disclosure must be grounded in implementation facts and visible at the upload decision point. Evidence from the dashboard, evidence worker, media adapter, deployment docs, and extraction gateway shows the pipeline is not local-only: originals are not automatically deleted by default, audio leaves the dashboard for Speakr/transcription, and text may leave for configured extraction/summary providers. Fact Checker verified Trinity's retention/Speakr claims but found the downstream ASR and ledger/note text hops were material omissions that must be disclosed before shipping.

### 2026-08-10: Speakr downstream transcription provider is deployment-configurable
**By:** Trinity
**What:** Speakr is configurable: the documented deployment sets `TRANSCRIPTION_API_KEY` and `TRANSCRIPTION_MODEL` for OpenAI transcription, while operators can use Speakr `ASR_BASE_URL` settings for a self-hosted ASR service.
**Why:** User-facing upload disclosure must say audio may go beyond Speakr to the configured transcription provider without falsely claiming every deployment uses the same provider. `deploy/OPERATIONS.md` documents OpenAI transcription variables, chunk behavior for audio sent per request, and `ASR_BASE_URL` for self-hosted ASR; `nix/containers.nix` says `speakr.env` holds cloud ASR/AI provider credentials populated out-of-band.

### 2026-08-11T02:05:00Z: Concurrent agents MUST use separate git worktrees
**By:** Scribe (from field experience)
**What:** Running two or more agents in the same checkout caused two real defects this session: (1) a Scribe commit landed on a feature branch instead of `main`; (2) one agent's branch was silently stacked on another's unmerged commit (would have double-merged and muddied both reviews). A third agent misreported a test count because another's in-flight files were present in the shared working tree. Pattern for spawning: `git worktree add /home/sspeaks/projects/acd-issue{N} squad/{N}-{slug}`, remove when done. Verified this round: Morpheus and Trinity worked independently with separate worktrees and both landed clean commits.
**Why:** Git worktrees provide isolated working directories with independent staging areas, HEAD, and file state. Concurrent agent work in the same checkout creates race conditions on branch state, test runs, and file existence. Scribe and coordinators cannot reliably synchronize mutable checkout state across concurrent tasks without serializing commits.

### 2026-08-11T02:05:00Z: Guards must be proven to fire, not merely to produce correct output
**By:** Scribe (from field experience)
**What:** An untested log/warning line has no evidence it executes — this codebase shipped an unreachable warning on #30 that silently reintroduced the bug it guarded against. Tests for guard branches MUST assert on the log record (`caplog`), and reviewers must mutate the guard to confirm the test goes red. Demonstrated: PR #33 added `test_consolidation_singleton_truncates_long_topic` asserting caplog fired when title exceeded limit, catching edge case where bare `[:200]` slice appeared complete.
**Why:** Code reviewers cannot visually verify control flow reaches a particular branch without executing it under test. Silent truncation, error fallbacks, and defensive rewrites often live in guard branches that aren't exercised by happy-path tests. Guards that produce correct output by accident (e.g., the slice happens to land at a word boundary) fail silently when input changes slightly.

### 2026-08-11T02:05:00Z: Schema-boundary mismatches are a recurring bug class
**By:** Scribe (from field experience)
**What:** A value validated against one model's constraints passed into another model with tighter constraints raises an unhandled `ValidationError`. Found twice in one file: (1) `_coerce_summary` title field (200-char limit on fallback titles); (2) `_coerce_consolidation` canonical_topic field (300-char limit on singleton topics). Both fixed by truncating at storage boundary with `[:197]+"…"`. When adding cross-model field flows, check receiving constraint against sending constraint — lengths, enums, optionality, numeric bounds.
**Why:** Schema-aware frameworks (Pydantic) define per-model validation. When one model produces a field that another model consumes, mismatches are common because constraints evolve independently. Catching them requires explicit trace of field flow: "topic produced by X with constraint Y passed to Z with constraint Z', check Z' >= Y".

### 2026-08-11T02:05:00Z: Truncate user-facing text with `[:N-3] + "…"`, never a bare slice
**By:** Scribe (from field experience)
**What:** Applied to both `_coerce_summary` fallback titles and `_coerce_consolidation` singleton topics. Coaching text is qualifier-dense; "unless the tenors are still scooping" and "unless the tenors" are different instructions. A bare cut reads as a complete thought and can mislead users. The ellipsis signals continuation and directs the user to the audio moment.
**Why:** Non-technical quartet members depend on coaching feedback for real-time vocal adjustment. Truncated text without visual indication becomes a silent contract violation — users read "feedback is XYZ" when the system stored "feedback is XYZ [truncated]". The `…` is cheap visual honesty.

### 2026-08-11T02:05:00Z: Eval fixtures must default to failure, not permission
**By:** Scribe (Switch original analysis from PR #34)
**What:** The over-merge fixture originally listed must-stay-distinct pairs, so any unlisted pair could be merged undetected (Tier 1 strategy: "merging is permitted unless listed"). Inverted (#32) to generate the full C(n,2) matrix minus explicitly permitted merges (Tier 2: "merging is forbidden except listed"). With 11 entries, this produces 54 active distinct constraints automatically. Unlisted pairs automatically fail; new entries participate without manual pair enumeration.
**Why:** Fixtures that enumerate known-bad cases only catch attacks someone already thought of. The full matrix closes the gap structurally, not incrementally. Attacks B, C, D, F (all unnamed at fixture authoring time) are now caught. Irreducible gap remains: fixture tests only the 11-entry quartet-coaching-01 session; production over-merges on novel sessions are not caught. Gap documented in `_coverage_notes`.

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction
