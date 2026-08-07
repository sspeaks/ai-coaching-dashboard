### 2026-08-07T10:32:42.057-07:00: Structured extraction uses a separate OpenAI gateway
**By:** Neo
**What:** Added an optional `extraction-gateway` FastAPI service that implements the existing `http_json` extraction contract, authenticates inbound bearer requests, calls OpenAI with JSON schema structured output, and validates returned ledger entries against `coaching_contracts` before returning them to the worker.
**Why:** Seth chose a separate gateway to keep a vendor boundary around transcript text. The worker can stay vendor-neutral while the gateway owns provider credentials, citation validation, and OpenAI-specific response handling.

### 2026-08-07T12:12:18.011-07:00: Gateway rejection counts remain contract-compatible
**By:** Neo
**What:** Added warning logs for model entry citation rejections and returned `model_entry_count` / `rejected_entry_count` top-level metadata while also copying those counts into surviving entries' `extraction_metadata`.
**Why:** The evidence API `http_json` client reads `payload["entries"]` and validates only each entry, so extra top-level keys are compatible while making silent drops observable for operators and future callers.
