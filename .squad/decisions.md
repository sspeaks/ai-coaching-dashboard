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

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction
