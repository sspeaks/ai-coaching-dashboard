## UX Review — PR #58 friendly recording status ladder — 2026-08-12T17:49:51.136-07:00
Viewports: 390x844, 360x800, 1440x900
Verdict: 🟢 APPROVE

I formed this verdict from my own rendered screenshots in this directory, not from Link's committed capture. I read issue #40, PR #58, and original Mouse finding #5 first, then judged the visible UI from pixels as a singer moving through the ladder.

### Original finding checked

Finding #5 from `.squad/files/ux-review/2026-08-12/REVIEW.md`: pipeline terms like “transcription in progress,” “Source recording,” and file/status details were too prominent. Suggested fix: use a friendly ladder and keep technical terms in optional detail.

### Task walkthrough

1. Uploading → ✅ Obvious. `03-upload-in-progress-uploading.png` shows “Uploading…” with progress. `04-feedback-uploading.png` shows “Uploading” as the primary recording status.
2. Listening to the recording → ✅ Obvious. `05-feedback-listening.png` uses “Listening to the recording” as the headline/status and explains this takes a few minutes.
3. Writing coaching notes → ✅ Obvious. `06-feedback-writing.png` uses “Writing coaching notes” and explains notes are being prepared.
4. Ready to read → ✅ Obvious. `07-feedback-ready.png` shows coaching notes are open and ready. Note: this follows the product glossary in issue #40 comments (“Ready to read” / “Ready”), even though the older shorthand sometimes said “Ready to review.”
5. Needs help → ✅ Obvious. `08-feedback-needs-help.png` uses “Needs help,” says “This file could not be read,” and gives “Upload a different file” / “Check again.”
6. Find technical detail when needed → ✅ Pass. Collapsed “Technical details” is visible in working/failed states; opening it reveals backend status such as TRANSCRIBING, RECONCILING, and FAILED.

### Evidence

Primary ladder screenshots:
- `phone-390x844/03-upload-in-progress-uploading.png`
- `phone-390x844/04-feedback-uploading.png`
- `phone-390x844/05-feedback-listening.png`
- `phone-390x844/06-feedback-writing.png`
- `phone-390x844/07-feedback-ready.png`
- `phone-390x844/08-feedback-needs-help.png`
- Matching 360 and desktop captures are under `narrow-phone-360x800/` and `desktop-1440x900/`.

Technical-detail screenshots:
- `phone-390x844/05-feedback-listening-technical-details-open.png`
- `phone-390x844/06-feedback-writing-technical-details-open.png`
- `phone-390x844/08-feedback-needs-help-technical-details-open.png`
- Matching desktop technical-detail captures are included.

### Acceptance criteria check

| Criterion | Verdict | Screenshot evidence | Notes |
|---|---|---|---|
| Every status rung is reachable/rendered | ✅ Pass | `03`–`08` screenshots across all viewports | Uploading, Listening, Writing, Ready, and Needs help all appear. |
| Friendly label is primary | ✅ Pass | `05-feedback-listening.png`, `06-feedback-writing.png`, `08-feedback-needs-help.png` | The large headings/badges use singer language. |
| Pipeline term remains secondary, not deleted | ✅ Pass | `*-technical-details-open.png` | Technical status remains in collapsed details. |
| Failure state is clear | ✅ Pass | `08-feedback-needs-help.png` | “Needs help” plus specific recovery actions are visible. |
| No #59 wording conflict | ✅ Pass | `01-feedback-empty-first-run.png`, `05-feedback-listening.png`, `07-feedback-ready.png` | #59 says “We listen…” then notes appear; #58 says “Listening…” then “Ready to read.” This reads consistently. |
| No 360px overflow or unmarked truncation | ✅ Pass | `narrow-phone-360x800/*.png` | Text wraps; the upload filename uses explicit ellipsis. |

### Findings

No blocking UX findings from screenshots. PR #58 resolves the copy problem: the primary path now reads as singer-facing work states, while technical pipeline terms are still findable in optional details.

Cross-stream note: PR #58 does not visibly contradict the approved first-run copy from PR #59. The PR #60 optional-review helper wording is not visible in this branch's rendered screenshots, so I cannot use pixels here to confirm that exact helper was reconciled.

### What screenshots cannot verify

Morpheus/code review owns these non-pixel questions. From screenshots alone I cannot verify:

- whether the ladder labels are driven by real job state rather than hardcoded strings;
- whether every backend state maps to the correct visible rung in production;
- whether status changes update live without stale labels;
- whether collapsed technical details include all operator-needed data for real errors;
- whether localization, screen-reader labels, and focus order match the visible wording;
- whether merged PR #60's optional-review helper text is reconciled if it is not present in this branch's pixels.
