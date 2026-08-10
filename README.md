# AI Coaching Dashboard

Evidence-grounded review of recorded coaching sessions. The system retains the
original media, sends transcription work to Speakr, imports immutable transcript
revisions, extracts claims with validated evidence spans, and requires human
review before the ledger is treated as complete.

## Architecture and boundaries

```text
browser -> Caddy/OIDC -> React UI + credential-checking gateway -> FastAPI
                                      FastAPI <-> PostgreSQL/media storage
                                      worker -> Speakr -> extraction provider
```

Speakr is an independent upstream service. This repository does not vendor,
modify, rebuild, or relicense it; the NixOS module deploys the pinned official
image and integrates only through its documented `/api/v1` API and signed
webhooks. Speakr remains subject to its own license. This repository currently
has no root license file, so do not infer a license for its code.

## Prerequisites

- Python 3.12 (the package supports 3.11+, but CI uses 3.12)
- Node.js 22 and npm
- Nix on Linux for reproducible packages, images, checks, or NixOS deployment
- Speakr and extraction-provider credentials only when exercising the full
  processing pipeline

## Local development

Backend API:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[test,postgres]'
EVIDENCE_ENVIRONMENT=development \
EVIDENCE_AUTH_MODE=development \
EVIDENCE_DATABASE_URL=sqlite:///./evidence.db \
.venv/bin/uvicorn evidence_api.app:app --reload
```

Worker (a second terminal, with the same provider/database environment):

```sh
EVIDENCE_ENVIRONMENT=development \
EVIDENCE_AUTH_MODE=development \
EVIDENCE_DATABASE_URL=sqlite:///./evidence.db \
.venv/bin/python -m evidence_worker
```

Frontend:

```sh
cd apps/web
npm ci
VITE_API_MODE=mock npm run dev
```

Mock mode is an explicitly labelled, synthetic UI-only demo. API mode uses the
same-origin `/api` contract and is normally run behind the deployment proxy;
the Vite configuration does not provide an API proxy.

## Tests and quality gates

These commands match `.github/workflows/test.yml`:

```sh
python3 -m pip install '.[test]'
python3 -m pytest
python3 -m unittest -v tests.api.test_live_api_contract

(cd apps/web && npm ci && npm test && npm run typecheck && npm run build)

python3 -m unittest discover -s tests/fixtures -v
python3 -m unittest discover -s tests/eval -v
python3 -m eval.score \
  --gold fixtures/synthetic/quartet-coaching-01/gold-ledger.json \
  --predicted fixtures/synthetic/quartet-coaching-01/gold-ledger.json \
  --transcript fixtures/synthetic/quartet-coaching-01/transcript.json
python3 -m unittest discover -s tests/browser -v

python3 -m unittest discover -s tests/nix -v
nix flake check --print-build-logs
```

See [eval/README.md](eval/README.md) for scoring gates, the adversarial fixture,
and disposable-deployment API acceptance.

## Nix packages and NixOS module

The flake supports `x86_64-linux` and `aarch64-linux` and exports
`nixosModules.aiCoaching` (also `nixosModules.default`), a development shell,
application packages, and OCI image archives:

```sh
nix flake show
nix develop
nix build .#evidence-backend
nix build .#web-frontend
nix build .#evidence-api-image
nix build .#evidence-worker-image
nix build .#web-frontend-image
```

Import `inputs.ai-coaching-dashboard.nixosModules.aiCoaching` and configure
`services.aiCoaching`; start from
[deploy/example-configuration.nix](deploy/example-configuration.nix). The
complete deployment, Speakr bootstrap, backup/restore, retention, and upgrade
procedure is in [deploy/OPERATIONS.md](deploy/OPERATIONS.md).

## Security and workflow

Development auth is loopback-only. Production uses Caddy plus oauth2-proxy OIDC,
stripped-and-rebuilt identity headers, and an independent shared hop credential
checked by both the gateway and application. Speakr tokens, webhook secrets,
OIDC/PostgreSQL credentials, and transcription/extraction provider keys are
server-side secrets: supply them out of band in root-readable runtime files or a
secret manager, never in source, Nix expressions/the Nix store, browser code,
or logs.

The normal workflow is upload -> Speakr transcription -> transcript
reconciliation -> evidence extraction -> human review. Provider speaker labels
remain unverified metadata. Transcript editing stays in Speakr; **Refresh from
Speakr** imports changes as a new immutable revision and regenerates the ledger.

### Known Speakr limitation

Speakr's upload API has neither an idempotency key nor lookup by client operation
ID. If a worker dies after a non-idempotent operation may have succeeded but
before its result is committed, the dashboard fails the job with
`ambiguous_provider_operation` rather than risking a duplicate. An administrator
must inspect Speakr and resolve the operation through
`POST /api/sessions/{session_id}/upload-operation/resolve` by adopting the
existing recording or explicitly recording an audited “not created” decision,
then refresh or retry processing.
