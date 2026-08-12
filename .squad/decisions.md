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

### 2026-08-12: Mouse UX review remediation triage
**By:** Morpheus
**What:** Filed Mouse's 2026-08-12 screenshot-only UX review as nine separate Link-owned issues: #36 and #37 are `priority:p0` / `release:v0.4.0`; #38 and #39 are `priority:p1` / `release:v0.4.0`; #40 is `priority:p1` / `release:v0.5.0`; #41 and #42 are `priority:p2` / `release:v0.5.0`; #43 and #44 are `priority:p2` / `release:v0.6.0`. Only #43 also gets `type:bug` because it is a visibly clipped UI element.
**Why:** Mouse's 🔴 verdict identifies two failed primary tasks: users cannot confidently jump to a critical audio moment (#36) or recover from a failed recording (#37), so those block v0.4.0. The note-reading/mobile-scroll defects (#38/#39) materially affect the same coaching journey and should land with the blocking fixes. Language, disclosure, review-control, and first-run polish remain important but can be staged into v0.5.0/v0.6.0 without hiding or vetoing Mouse's findings. Link owns the remediation; Trinity remains locked out by reviewer rejection protocol.

### 2026-08-12: Timestamp jump and failure recovery block singer tasks
**By:** Mouse
**What:** First screenshot-only UX review is 🔴 Illegible because two primary singer tasks fail from pixels alone: timestamp chips do not clearly play/jump the source recording, and the failed-recording state does not provide an actionable recovery path.
**Why:** The product promise depends on hearing the coach at critical timestamps and recovering from bad uploads. If timestamp controls look like citations and failures only say to check again after an unspecified issue is fixed, non-technical singers will stall.

### 2026-08-12T21-24-02: Added Mouse (UX Review Engineer) — reviews UI via screenshots only, no source code
**By:** squad-coordinator
**What:** Added Mouse (UX Review Engineer) — reviews UI via screenshots only, no source code
**References:** Mouse, Trinity, Switch, Tank, .squad/agents/mouse/charter.md
**Why:** Requested by Seth Speaks on 2026-08-12.

**What:** Added Mouse as UX Review Engineer to the ai-coaching-dashboard squad.

**Method (the defining constraint):** Mouse reviews the UI using ONLY rendered screenshots at phone (390x844, 360x800) and desktop (1440x900) viewports. While forming a verdict, Mouse may not read HTML, JSX/TSX, CSS, JS, DOM dumps, aria-labels, or any source. If a first-time user cannot figure out what to do from the pixels alone, that is a UI defect. Source code may only be read AFTER the verdict is written, and only to route the fix to the right file — the verdict never changes based on code.

**Verdicts:** Legible (green) / Ambiguous (yellow) / Illegible (red). Any primary-task step that cannot be determined from screenshots is automatically red.

**Boundaries:** Mouse does not implement fixes (Trinity owns UI implementation) and does not own functional/E2E correctness (Switch owns that). Mouse owns screenshot capture, comprehension verdicts, UX defect reports, and visual regression baselines under `.squad/files/ux-review/`.

**Open dependency:** No headless-browser screenshot tooling (Playwright or equivalent) is installed in this repo as of 2026-08-12. Mouse cannot issue a real verdict until capture works against `apps/web`. "Couldn't capture" is never "passed."

**Files changed:** `.squad/agents/mouse/charter.md`, `.squad/agents/mouse/history.md`, `.squad/team.md`, `.squad/routing.md`, `.squad/casting/registry.json`, `.squad/casting/history.json`.

### 2026-08-12T21-46-34: UX review 🔴 — Trinity locked out per Reviewer Rejection Protocol; Link cast to own remediation
**By:** squad-coordinator
**What:** UX review 🔴 — Trinity locked out per Reviewer Rejection Protocol; Link cast to own remediation
**References:** Mouse, Link, Trinity, Morpheus, .squad/files/ux-review/2026-08-12/REVIEW.md
**Why:** Requested by Seth Speaks on 2026-08-12.

**Context:** Mouse's first Screenshot-Only Comprehension Test returned 🔴 Illegible on the existing web UI (report: `.squad/files/ux-review/2026-08-12/REVIEW.md`). Two primary user tasks are unachievable from the screens alone: jumping back to a critical audio moment, and recovering from a failed recording.

**Decision:** The Reviewer Rejection Protocol is enforced STRICTLY, even though this was a baseline audit of pre-existing UI rather than a rejection of a freshly-produced artifact. The user was offered the option to waive the lockout for Trinity and explicitly chose to cast a new agent instead.

**Consequences:**
1. Trinity (original author of the reviewed UI) is LOCKED OUT of all 9 UX remediation findings.
2. Link was cast as Frontend Engineer (UX Remediation) — charter at `.squad/agents/link/charter.md`. Link owns rejected-UI revisions going forward; Trinity retains original feature implementation.
3. All 9 findings are filed as individual GitHub issues labeled `squad:link` + `type:ux`, triaged by Morpheus.
4. Mouse re-reviews from FRESH screenshots after fixes land. A described fix is never accepted in place of captured evidence.
5. If Link's revision is itself rejected, Link is locked out of the next cycle and a third agent takes it.

**Rationale for strict enforcement:** The value of the screenshot-only review is that it is adversarial and independent. Letting the original author fix their own rejected work reintroduces the exact bias the method exists to remove — the author knows what the control does, so they cannot see that the pixels fail to say it.

**Precedent set:** UX review rejections trigger author lockout in this repo by default. Waiving it requires explicit user approval.

### 2026-08-12: UX capture uses Nix Playwright browsers with npm Playwright driver
**By:** Tank
**What:** The web UX screenshot harness uses the npm `playwright` package pinned exactly to `1.61.1`, matching `nixpkgs#playwright-driver.version`. The flake dev shell declares `playwright-driver.browsers` and exports `PLAYWRIGHT_BROWSERS_PATH` plus `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`. The harness resolves Chromium from that Nix browser path and passes it as `executablePath`.
**Why:** This keeps browser binaries declarative and avoids hand-installed global Playwright downloads. Passing the executable path also avoids npm/Nix Playwright revision mismatches while preserving a normal `npm run ux:capture` entry point for Mouse.

### 2026-08-12: Mock UI states are pinned with `mockState` URLs
**By:** Trinity
**What:** In mock mode, screenshot-specific UI states are selected with deterministic `mockState` query parameters instead of time-based transitions. The upload form has a dedicated held `mockState=upload-progress`; session states use real backend state values or aliases that map to real state values.
**Why:** Mouse reviews screenshots only, and Tank's harness needs stable URLs that render byte-identical content across runs without waiting for timers, uploads, or backend jobs.

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction
