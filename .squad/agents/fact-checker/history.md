# Project Context

- **Project:** ai-coaching-dashboard
- **Created:** 2026-08-07

## Core Context

Agent Fact Checker initialized and ready for work.

## Recent Updates

📌 Team initialized on 2026-08-07

## Learnings

Initial setup complete.

## 2026-08-10T14:42-07:00 — PR #9 upload disclosure verification

- Verified PR #9 disclosure claims against evidence API, worker, Speakr adapter, Nix deployment, and ops docs.
- Bottom line: deletion/storage claims are accurate, but the copy materially omits downstream external processing: Speakr may send audio to its configured ASR/transcription provider, and summary generation sends ledger text to the AI extraction gateway.
- Posted verification report on PR #9 and requested a blocking copy correction before ship.
📌 Team update (2026-08-10T14:08:35-07:00): Upload disclosure verification established a durable fact: dashboard storage/deletion claims are mostly accurate, but downstream ASR plus transcript/ledger/note text processing must be disclosed — decided by Fact Checker
