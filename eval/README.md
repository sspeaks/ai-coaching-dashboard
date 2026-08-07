# Quality gates

All bundled material is synthetic and redistributable. No private or copyrighted
recording is required.

## Deterministic ledger evaluation

```bash
python3 -m unittest discover -s tests/fixtures -v
python3 -m unittest discover -s tests/eval -v
python3 -m eval.score \
  --gold fixtures/synthetic/quartet-coaching-01/gold-ledger.json \
  --predicted path/to/generated-ledger.json \
  --transcript fixtures/synthetic/quartet-coaching-01/transcript.json
```

The scorer exits nonzero unless all gates pass:

| Metric | Gate |
|---|---:|
| Labelled intervention recall | >= 90% |
| Unsupported claim rate | 0% |
| Reversed critical instructions | 0 |
| Invented critical claims | 0 |
| Subject attribution accuracy | >= 95% |
| Relevant evidence links | >= 95% |
| Median evidence seek error | <= 2 seconds |
| Uncertainty compliance | 100% |
| Verification-state accuracy | >= 95% |
| Substantive entries with evidence | 100% |
| Transcript revision match | 100% |

Generated results must use the normalized fixture fields. An integration adapter
may map API fields to this format, but must not infer missing subjects, actions,
quotes, outcomes, uncertainty, or evidence.

The adversarial fixture must fail:

```bash
! python3 -m eval.score \
  --gold fixtures/synthetic/quartet-coaching-01/gold-ledger.json \
  --predicted fixtures/synthetic/quartet-coaching-01/adversarial-ledger.json \
  --transcript fixtures/synthetic/quartet-coaching-01/transcript.json
```

## Black-box API acceptance

The endpoint profile is `fixtures/contracts/evidence-api-profile.json`. Update
that profile, not the tests, when stable endpoint paths differ.

```bash
EVIDENCE_API_BASE_URL=http://127.0.0.1:8000 \
EVIDENCE_API_TOKEN=... \
EXPECTED_TRANSCRIPTION_PROVIDER=disabled \
EVIDENCE_WORKER_RESTART_COMMAND='systemctl restart evidence-worker' \
python3 -m unittest discover -s tests/api -v
```

The suite checks full upload/download integrity, persisted idempotency across a
worker restart, transcript revision preservation and ledger regeneration,
configured-copy deletion with audit, provider-egress policy, and runtime,
storage, and provider-API-cost metrics. It is skipped when no deployed API URL
is supplied. Use only a disposable test deployment.

## Browser and NixOS

Browser automation can implement the stable scenarios in
`fixtures/browser/evidence-ledger-scenarios.json`. Validate their coverage with:

```bash
python3 -m unittest discover -s tests/browser -v
```

NixOS static/export checks:

```bash
python3 -m unittest discover -s tests/nix -v
nix flake check --print-build-logs
```

The flake must expose fresh-deploy and backup-restore VM checks. Those checks
must exercise a blank state directory, retained original media, database and
media backup, restore onto a fresh instance, authentication proxy wiring, and
service health after restore.
