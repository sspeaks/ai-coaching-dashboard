# Evidence backend MVP

The FastAPI service owns recordings, workflow state, transcript revisions,
evidence-grounded ledger entries, and human verification. Speakr remains an
independent pinned service and is used only through `/api/v1` plus signed
webhooks. Provider speaker labels are stored as unverified evidence metadata.
All API timestamps into media are integer milliseconds; Speakr seconds are
rounded to the nearest millisecond.

The browser contract is rooted at `/api`. Creating a session and posting
multipart field `media` to `/api/sessions/{id}/media` durably queues the full
transcribe -> status/reconcile -> extract chain. Playback remains at the stable
authenticated URL `/api/sessions/{id}/media`. A manual
`POST /api/sessions/{id}/refresh` imports Speakr edits as a new immutable
transcript revision and re-extracts the current ledger when content changed.

## Run locally

```bash
python -m venv .venv
.venv/bin/pip install -e '.[test,postgres]'
EVIDENCE_ENVIRONMENT=development \
EVIDENCE_AUTH_MODE=development \
EVIDENCE_DATABASE_URL=sqlite:///./evidence.db \
.venv/bin/uvicorn evidence_api.app:app --reload
```

In another process:

```bash
EVIDENCE_ENVIRONMENT=development \
EVIDENCE_AUTH_MODE=development \
EVIDENCE_DATABASE_URL=sqlite:///./evidence.db \
.venv/bin/python -m evidence_worker
```

Production should use PostgreSQL, a shared persistent media volume with backup,
and forwarded identity/group headers set only by an edge proxy (e.g.
oauth2-proxy via Caddy) from a configured trusted proxy network (loopback by
default; see `nix/containers.nix`, which places a dedicated Go gateway in
front of this service). In `trusted_proxy` mode, every request must
additionally present a credential-backed shared secret in the header named by
`EVIDENCE_TRUSTED_PROXY_SECRET_HEADER` (default
`X-AI-Coaching-Proxy-Auth`), matching `EVIDENCE_TRUSTED_PROXY_SHARED_SECRET`
exactly (constant-time comparison). This is independent, application-level
defense-in-depth against a peer container on the same network reaching this
service directly and forging identity headers: without a correctly configured
secret, every request is rejected, regardless of client IP or identity
headers presented -- fail closed, not fail open. `development` auth mode has
no credential at all and is therefore only ever accepted from loopback
connections, both by the deployment's network topology and by this
application independently. See `config.example.env` for the full set of
`EVIDENCE_TRUSTED_*` variables and their intended values; the secret itself
must come from a secret manager, never from source control or logs.
Unmatched authenticated users are viewers; configured editor groups may
create, upload, refresh, cancel, and verify; configured admin groups
additionally perform two-step deletion. Configure Speakr's documented
webhook events to POST to `/api/webhooks/speakr`; store the one-time
webhook secret in `EVIDENCE_SPEAKR_WEBHOOK_SECRET`. API tokens are server-side
only.

Schema creation is deterministic and idempotent at API/worker startup. A
deployment migration tool remains required before evolving this MVP schema.
Original media is retained until `DELETE /api/sessions/{id}` followed by explicit
`POST /api/sessions/{id}/deletion/confirm` with the matching session id.
`DELETE` persists a deletion tombstone immediately (independent of the
session/job rows themselves) and cancels any job that has not yet started;
this tombstone is what lets a worker that is already mid-upload to Speakr, in
a separate transaction, detect the cancellation and compensate instead of
leaking an orphaned provider recording. If a job is still actively RUNNING
(within `EVIDENCE_WORKER_JOB_LEASE_SECONDS` of its last update) when
confirmation is requested, the endpoint truthfully responds `202 Accepted`
with `{"code": "deletion_pending_active_job"}` instead of deleting anything or
claiming success; retry confirmation once the job is no longer active.
Confirmation only proceeds to delete the Speakr copy (404 is idempotent
success) and the retained project copy once no such in-flight job remains,
returning `204`. If Speakr deletion fails, the project copy remains and the
API returns a clear error. Backup deletion/retention must be implemented by
the deployment's backup policy.

Structured extraction defaults to `disabled` and fails explicitly. The
`http_json` provider calls a project-controlled gateway and validates every
returned evidence reference before persistence: an evidence reference must
cover the *complete* span of every transcript segment it cites (not merely
overlap it), since this backend does not currently support independently
validated word-level timestamps that would justify trusting a narrower
sub-range.

## Test

```bash
.venv/bin/pytest
```
