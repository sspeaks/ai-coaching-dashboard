# Extraction Gateway

Small FastAPI service that implements the evidence API's `http_json` structured
extraction contract. It authenticates inbound requests with a shared bearer
token, sends transcript segments to OpenAI using structured JSON output, and
validates returned ledger entries against `coaching_contracts`.

The response includes `model_entry_count` and `rejected_entry_count` in addition
to the contract-required `entries`; the evidence API's `http_json` client reads
only `entries`, so this remains backward-compatible while making dropped model
entries observable. Surviving entries also receive those counts in
`extraction_metadata`.

`confidence` is model-self-reported and uncalibrated. Treat it as a model hint,
not a real probability or reviewed correctness score.

## Required environment

- `EXTRACTION_GATEWAY_OPENAI_API_KEY` (secret)
- `EXTRACTION_GATEWAY_INBOUND_API_KEY` (secret; same value the worker uses as
  `EVIDENCE_EXTRACTION_API_KEY`)

Optional:

- `EXTRACTION_GATEWAY_OPENAI_MODEL` (default `gpt-4o`)
- `EXTRACTION_GATEWAY_OPENAI_BASE_URL` (default `https://api.openai.com/v1`)
- `EXTRACTION_GATEWAY_REQUEST_TIMEOUT_SECONDS` (default `120`)
