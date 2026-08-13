# Friendly status ladder for singer-facing recording state

**Date:** 2026-08-12T17:49:51.136-07:00
**By:** Link
**Issue:** #40

## Decision

Primary singer-facing recording status uses one ladder everywhere: **Uploading**, **Listening to the recording**, **Writing coaching notes**, **Ready to read**, and **Needs help**. Backend states, transcript/provider terms, and failure diagnostics stay available only in collapsed technical details, management controls, or recovery detail copy.

## Why

Barbershop singers need to know whether the app is sending audio, listening, preparing notes, ready, or asking for help. Pipeline words like transcription, reconciliation, extraction, and failed/error are useful to operators but make the main path feel like a backend console.

## Evidence

Implemented and tested in issue #40 with dynamic App tests for CREATED, UPLOADING, UPLOADED, TRANSCRIBING, RECONCILING, TRANSCRIPT_READY, EXTRACTING, RETRY_PENDING, AWAITING_REVIEW, COMPLETE, and FAILED.
