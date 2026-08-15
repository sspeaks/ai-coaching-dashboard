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
**What:** Running two or more agents in the same checkout caused wrong-branch commits, silently stacked branches, and misleading test counts. Spawn concurrent work in separate worktrees such as `/home/sspeaks/projects/acd-issue{N}` and remove them when done.
**Why:** Git worktrees provide isolated working directories with independent staging areas, HEAD, and file state. Concurrent agent work in the same checkout creates race conditions on branch state, test runs, and file existence. Scribe and coordinators cannot reliably synchronize mutable checkout state across concurrent tasks without serializing commits.

### 2026-08-11T02:05:00Z: Guards must be proven to fire, not merely to produce correct output
**By:** Scribe (from field experience), Switch
**What:** Guard branches and behavior assertions must be proven to fail under mutation before they are trusted. For warning/log guards, assert on the log record (`caplog`) and mutate the guard to confirm the test goes red. For UI behavior guards, mutate the protected behavior or selector so the test visibly fails.
**Why:** Code reviewers cannot visually verify control flow reaches a particular branch without executing it under test. Silent truncation, error fallbacks, defensive rewrites, and dynamic UI behaviors often pass happy-path tests while the intended guard never runs.

### 2026-08-11T02:05:00Z: Schema-boundary mismatches are a recurring bug class
**By:** Scribe (from field experience)
**What:** A value validated against one model's constraints passed into another model with tighter constraints raises an unhandled `ValidationError`. When adding cross-model field flows, check receiving constraint against sending constraint — lengths, enums, optionality, numeric bounds.
**Why:** Schema-aware frameworks define per-model validation. When one model produces a field that another model consumes, mismatches are common because constraints evolve independently.

### 2026-08-11T02:05:00Z: Truncate user-facing text with `[:N-3] + "…"`, never a bare slice
**By:** Scribe (from field experience)
**What:** User-facing text truncation must reserve space for an ellipsis and append `…`; bare slicing is not acceptable.
**Why:** Coaching text is qualifier-dense. A bare cut can read as a complete thought and mislead users; the ellipsis signals continuation and directs the user to the audio moment or detail source.

### 2026-08-11T02:05:00Z: Eval fixtures must default to failure, not permission
**By:** Scribe (Switch original analysis from PR #34)
**What:** Eval fixtures should generate the full C(n,2) matrix of forbidden merges and list only explicitly permitted merges as exceptions. Unlisted pairs must fail automatically; new entries must participate without manual pair enumeration.
**Why:** Fixtures that enumerate known-bad cases only catch attacks someone already thought of. The full matrix closes the gap structurally, not incrementally.

### 2026-08-12: Timestamp jump and failure recovery block singer tasks
**By:** Mouse
**What:** Timestamp playback and failed-recording recovery are primary singer tasks. If users cannot tell from the UI how to jump back to a coaching moment or recover from a failed recording, the experience is blocked.
**Why:** The product promise depends on hearing the coach at critical timestamps and recovering from bad uploads. If timestamp controls look like citations and failures only say to wait after an unspecified issue is fixed, non-technical singers stall.

### 2026-08-12T21-24-02: Mouse reviews UI via screenshots only, no source code
**By:** squad-coordinator
**What:** Mouse is the UX Review Engineer. Mouse forms verdicts using only rendered screenshots at phone (390x844, 360x800) and desktop (1440x900) viewports. Source code may be read only after the verdict is written, and only to route fixes.
**Why:** If a first-time user cannot figure out what to do from the pixels alone, that is a UI defect. Source knowledge must not rescue an ambiguous screenshot.

### 2026-08-12T21-46-34: UX review rejections trigger author lockout by default
**By:** squad-coordinator
**What:** The Reviewer Rejection Protocol applies strictly to UX screenshot rejections in this repo. Trinity was locked out of the rejected baseline UX remediation, Link was cast to own the revisions, and any later rejected revision locks out that revision's author for the next cycle unless Seth explicitly waives the lockout.
**Why:** Screenshot-only review is adversarial and independent. Letting the original author fix rejected UI by default reintroduces the bias the method exists to remove: the author already knows what the control does.

### 2026-08-12: Mock UI states are pinned with `mockState` URLs
**By:** Trinity
**What:** In mock mode, screenshot-specific UI states are selected with deterministic `mockState` query parameters instead of time-based transitions. The upload form has a dedicated held `mockState=upload-progress`; session states use real backend state values or aliases that map to real state values.
**Why:** Mouse reviews screenshots only, and Tank's harness needs stable URLs that render byte-identical content across runs without waiting for timers, uploads, or backend jobs.

### 2026-08-12: Timestamp activation must keep visible now-playing feedback near the note
**By:** Morpheus
**What:** On phone, tapping a timestamp must not move focus away from the requesting note to the audio element. The selected timestamp changes to “Now playing…”, the requesting note gets an inline now-playing cue with a visible mini playhead, and the source-recording area mirrors the same cue when sticky/visible.
**Why:** Mouse rejected PR #45 because labels made the pre-touch affordance obvious, but phone users still could not see what happened after touch. Open-feedback behavior owns the detail scroll/focus; timestamp play owns only in-note/player feedback.

### 2026-08-12: UX capture determinism includes the first clean-checkout run
**By:** Switch
**What:** UX screenshot harness validation must compare the documented clean-checkout command's first output against subsequent outputs; warming caches before the determinism run is not enough.
**Why:** PR #49's first clean `npm ci && ux:capture` output differed from later captures by 10 pixel-channel values in one desktop processing screenshot. Even tiny pixel drift can create false visual-regression gate failures if the first fresh-clone capture becomes a baseline.

### 2026-08-12: UX capture must verify flake-local Playwright browser alignment
**By:** Switch
**What:** The UX screenshot harness must compare the npm Playwright package/browser revisions against the flake-pinned Nix `playwright-driver.browsers`, not against the user's registry `nixpkgs#`.
**Why:** A harness can still produce screenshots under a browser/package mismatch, so the guard must fail loudly before Mouse treats captures as binding evidence.

### 2026-08-12: UX capture dev shell owns Playwright browsers and fonts
**By:** Tank
**What:** UX screenshot capture runs from the flake dev shell with Nix `playwright-driver.browsers`, `PLAYWRIGHT_BROWSERS_PATH`, `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`, and an explicit fontconfig bundle for Noto, Liberation, DejaVu, CJK, and emoji fonts.
**Why:** Mouse's screenshot gate must be reproducible on NixOS. Browser binaries must match npm Playwright, and missing fonts can silently corrupt screenshots even when Chromium launches.

### 2026-08-12T17:49:51.136-07:00: First-run guide
**By:** Link
**What:** The empty feedback detail panel should become the first-run guide when there are no recordings: a large “Upload your first rehearsal recording” callout, primary upload button, and a short “What happens next” preview.
**Why:** Mouse's desktop screenshot showed the original empty state left most of the page unused. Quartet singers need the blank space to explain the immediate action and the next result, while keeping the existing Feedback/Upload/Manage navigation visible.

### 2026-08-12: Ledger notes lead with coaching takeaway
**By:** Link, Switch
**What:** `LedgerReview` note cards lead with a plain-language Coaching takeaway section. Confidence, uncertainty/demo warnings, and optional review controls stay discoverable but lower in the hierarchy behind appropriately labeled disclosures. Tests for this hierarchy must fail if warnings move ahead of the takeaway or warnings disappear entirely.
**Why:** Issue #38 depends on content hierarchy, not mere presence. Singers need the coaching point before review mechanics while preserving warning and audit access.

### 2026-08-12T17:49:51.136-07:00: Friendly status ladder for singer-facing recording state
**By:** Link
**What:** Primary singer-facing recording status uses one ladder everywhere: **Uploading**, **Listening to the recording**, **Writing coaching notes**, **Ready to read**, and **Needs help**. Backend states, transcript/provider terms, and failure diagnostics stay available only in collapsed technical details, management controls, or recovery detail copy.
**Why:** Barbershop singers need to know whether the app is sending audio, listening, preparing notes, ready, or asking for help. Pipeline words like transcription, reconciliation, extraction, and failed/error are useful to operators but make the main path feel like a backend console.

### 2026-08-12: Frontend guards use stable structure, not literal copy
**By:** Link, Scribe
**What:** Frontend tests and capture waits must use stable `data-testid` hooks or role-based queries rather than exact user-facing copy whenever the assertion is guarding behavior or structure. Copy text can be asserted only when the copy itself is the behavior under test.
**Why:** Recovery/status copy is expected to evolve. Literal copy selectors can make guards brittle or, worse, let behavior protections pass vacuously after copy renames.

### 2026-08-12: Feedback disclosure controls keep their target mounted
**By:** Morpheus
**What:** The mobile “Read feedback” disclosure pattern must keep the controlled feedback-detail region mounted in the DOM even when no recording is open. Buttons may keep `aria-controls="feedback-detail-panel"`; the region swaps between empty/loading/open content and receives focus only after the selected detail has loaded.
**Why:** Issue #35 is a real user confusion report, so the disclosure semantics must be reliable for assistive technology as well as visual users. A dangling `aria-controls` reference after closing undermines the fix; keeping the region mounted also makes scroll/focus behavior predictable.

### 2026-08-12: Interaction-feel gate for timestamp/source playback controls
**By:** Morpheus
**What:** Future UX gates for timestamp/source playback controls must include behavior verification after activation at real phone scroll positions, not only static pre-click screenshots.
**Why:** Mouse's pixel gate can approve affordance/proximity while missing tap aftermath, sticky-control occupancy, or whether users can still pause/scrub immediately after activating a source moment.

### 2026-08-12T17:49:51.136-07:00: Reset redundant local main divergence before PR review
**By:** Morpheus
**What:** Local `main` must match `origin/main` before reviewing or merging follow-on PRs. Preserve `.squad/` state separately when resetting stale local divergence.
**Why:** Stale divergence caused scope-leaked diffs, misleading test counts, and red nixos-quality CI. Reviews must start from upstream truth; screenshots and green CI still require code-level verification before merge.

### 2026-08-12T17:49:51.136-07:00: Merge P0 fixes before overlapping lower-priority UX PRs
**By:** Morpheus
**What:** When a batch contains a P0/release-blocking PR and lower-priority PRs touching overlapping UI regions or styles, merge the P0 first. After each merge, re-check every remaining PR's mergeability and CI on the new base before trusting its green status.
**Why:** Individually verified PRs do not compose into a verified whole. Pre-existing green checks are invalid after any merge touching shared files; clean textual merges are not enough for user-visible UX defect classes.

### 2026-08-12T17:49:51.136-07:00: Summary source playback requires real media-event behavior
**By:** Morpheus
**What:** Summary-level source playback is accepted only when active state is compact (button plus sticky Source recording player), native `audio[controls]` remains visible near the advice, playhead progress is derived from real media time/duration, and pause/end/error clearing is wired to media events with mutation-tested regression coverage.
**Why:** PR #45 showed screenshots can hide hardcoded playhead values and stale active state. For source-playback UX, code review must prove dynamic media behavior rather than accepting a still image or green CI alone.

### 2026-08-12T17:49:51.136-07:00: UX gates must catch zero-size interactive controls
**By:** Morpheus, Mouse, Switch
**What:** Code review for `type:ux` PRs must not stop at DOM presence or correct data flow. Interactive controls must be verified as user-visible at target viewports: non-zero rendered size, visible, and not offscreen. Switch's `ux:control-guard` from PR #62 is authoritative for the zero-height/hidden/clipped/offscreen interactive-control bug class; PR #61 retains the focused audio evidence.
**Why:** PR #57 had correct React state, real currentTime/duration playhead logic, and an `audio[controls]` element in the DOM, but Mouse proved the phone native controls were effectively absent because Chromium laid the element out at 0px height. PR #62 proved the guard fails under that mutation and belongs in CI.

### 2026-08-12T17:49:51.136-07:00: Type:ux PRs require both code and screenshot gates before merge
**By:** Morpheus, Mouse, Switch
**What:** A `type:ux` PR must not be merged until both independent gates have reported: code/behavior review and Mouse's screenshot-only UX review. Green CI plus a passing code review is insufficient, and screenshots alone are also insufficient.
**Why:** PR #45 proved screenshots can miss hardcoded or stale dynamic behavior; PR #57 proved code review, 4 green CI checks, and 40 tests can miss a user-visible layout failure where native audio controls disappear on phone. The gates are complementary and both are required.

### 2026-08-12T17:49:51.136-07:00: Optional note review controls stay below coaching content
**By:** Mouse, Link
**What:** Note review controls should be collapsed by default after coaching/source content, visibly labeled “Optional: check this note,” and expand to large phone-friendly controls without overflow, empty panels, or unexpected collapse.
**Why:** The pattern keeps optional review discoverable without putting it in the main coaching path or distracting from reading.

### 2026-08-12: Deletion confirmation honors pending provider-write sections
**By:** Neo
**What:** `confirm_deletion` must defer while a TRANSCRIBE job is RUNNING with a durable `pending_operation_kind` (`upload` or `queue_transcription`), even if the heartbeat-based active lease is momentarily stale. Once that job reaches a terminal non-running state, confirmation may proceed.
**Why:** The provider-write marker is committed before non-idempotent upstream calls and cleared only with the durable outcome. Relying only on `updated_at >= lease_cutoff` lets heartbeat scheduling/SQLite timing delete a session while the worker is still inside the provider call, producing the observed 202-vs-204 race.

### 2026-08-12: UX capture pins npm Playwright to flake-pinned Nix Playwright 1.59.1
**By:** Neo
**What:** The UX screenshot harness aligns npm `playwright`/`playwright-core` with the flake-pinned Nix `playwright-driver` by pinning npm to `1.59.1`, the version currently provided by this repository's `flake.lock`. The dev shell exposes `PLAYWRIGHT_NIX_DRIVER_VERSION`, and the harness fails before capture if the npm package version, Nix driver version, or Chromium browser revision drift apart.
**Why:** Pinning npm down to the already-flake-pinned browser bundle keeps the browser binary declarative, keeps the npm lockfile honest, and turns future Nix bumps into loud failures instead of silent screenshot-rendering drift.

### 2026-08-12T23:47:17Z: PR #45 code gate requires mutation-capable timestamp tests
**By:** Switch, Trinity
**What:** Timestamp playback reviews must include mutation-capable assertions and browser-real play-promise coverage. Tests should prove playhead percentages are event-derived, that hardcoded constants fail, and that switching timestamps while audio is already playing follows the resolved `audio.play()` promise without requiring a second `play` event.
**Why:** This artifact previously passed screenshot/static tests with false playback state. Screenshot review cannot catch fabricated dynamic state, and a single fixed percentage assertion can re-encode a static playhead.

### 2026-08-12: PR #52 proximity is CSS/pixel-gated beyond DOM visibility
**By:** Switch
**What:** Unit tests can constrain that summary source-moment controls are rendered and disabled when audio is unavailable, but they cannot prove phone visual proximity, scrolling comfort, or sticky audio/control overlap. Pixel-distance and layout claims remain Mouse screenshot gates.
**Why:** The implementation change is mostly layout/CSS around summary moment controls. DOM tests mutation-prove visibility/disabled assertions, while actual phone proximity requires rendered evidence.

### 2026-08-12: Ignore UX capture PNGs only
**By:** Tank
**What:** Repo-root `.gitignore` ignores `.squad/files/ux-review/**/*.png`.
**Why:** UX capture PNGs are large, regenerable binaries that should not be swept into `git add -A`. The rule is image-only instead of a blanket `.squad/files/ux-review/` ignore so durable Mouse evidence such as `REVIEW.md` and `manifest.json` remains committable and existing tracked evidence stays untouched.

### 2026-08-12T17:49:51.136-07:00: Summary source playback uses active buttons plus compact sticky player
**By:** Trinity
**What:** Summary-level source moments should not insert a full inline NowPlayingCue after activation. The tapped button becomes the local “Now playing source at mm:ss” confirmation, while the sticky Source recording player carries the native audio controls and compact progress cue. Full theme summaries are not passed into playback cue source labels.
**Why:** The #54 regression came from combining always-visible summary source controls with a full-size cue that repeated the advice text. Keeping the confirmation in the button avoids layout jumps under repeated taps, preserves proximity to the advice, and keeps pause/scrub controls immediately reachable on phone.

### 2026-08-12: Summary source moments stay visible by default
**By:** Trinity
**What:** Main summary cards show their source-moment play buttons directly beside the advice instead of hiding them behind a collapsed disclosure. The dense all-notes ledger remains the drill-down for audit/review details.
**Why:** Issue #39 is about phone proximity between advice and audio. Keeping the play control in the same summary card preserves simplicity while reducing scroll/context loss; pixel proof remains Mouse's gate.

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction
