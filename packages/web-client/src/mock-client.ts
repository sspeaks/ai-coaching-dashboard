import type {
  CoachingIntervention,
  EvidenceApiClient,
  InterventionReview,
  SessionDetail,
  SessionOverview,
  SessionState,
  SessionSummary,
  UploadRequest,
  UploadTarget,
  UploadTicket,
  VerificationStatus,
} from "./types";

const silentAudio =
  "data:audio/wav;base64,UklGRiwAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQgAAACAgICAgICAgA==";

const fixedNow = "2026-08-12T18:30:00.000Z";
const fixedGeneratedAt = "2026-08-12T18:35:00.000Z";
const fixedUploadCreatedAt = "2026-08-12T18:40:00.000Z";

const stateAliases: Record<string, SessionState | "EMPTY" | "UPLOAD_PROGRESS"> = {
  empty: "EMPTY",
  "first-run": "EMPTY",
  "upload-progress": "UPLOAD_PROGRESS",
  created: "CREATED",
  uploading: "UPLOADING",
  uploaded: "UPLOADED",
  processing: "TRANSCRIBING",
  transcribing: "TRANSCRIBING",
  reconciling: "RECONCILING",
  "transcript-ready": "TRANSCRIPT_READY",
  extracting: "EXTRACTING",
  "awaiting-review": "AWAITING_REVIEW",
  awaiting_review: "AWAITING_REVIEW",
  complete: "COMPLETE",
  completed: "COMPLETE",
  reviewed: "COMPLETE",
  "retry-pending": "RETRY_PENDING",
  failed: "FAILED",
  error: "FAILED",
  cancelled: "CANCELLED",
  "delete-pending": "DELETE_PENDING",
  deleted: "DELETED",
};

function requestedMockState(): SessionState | "EMPTY" | "UPLOAD_PROGRESS" | null {
  if (typeof window === "undefined") return null;
  const raw = new URLSearchParams(window.location.search).get("mockState");
  if (!raw) return null;
  return stateAliases[raw.trim().toLowerCase()] ?? null;
}

function makeIntervention(
  id: string,
  topic: string,
  verificationStatus: VerificationStatus,
  startMs: number,
  overrides: Partial<CoachingIntervention> = {},
): CoachingIntervention {
  return {
    id,
    topic,
    exactCoachFeedback:
      "This is synthetic demo coaching: reset the vowel together before the tag so the chord can lock sooner.",
    interpretation:
      "The quartet should agree on the target vowel shape before the final phrase instead of each singer adjusting alone.",
    appliesTo: "Full quartet, with the lead and baritone checking matching vowels first",
    songReference: "Demo ballad, tag into the final held chord",
    problemBefore:
      "The harmony spread during the pickup, so the final chord sounded wider than intended.",
    exerciseOrRequestedChange:
      "Speak the lyric in rhythm, sing it on one pitch, then add harmony while keeping the same vowel.",
    observedResult:
      "The second attempt settled faster and the ringing overtone appeared earlier.",
    nextAction:
      "Quartet: rehearse the tag slowly twice before the next full run.",
    unresolvedQuestion:
      "Confirm whether the bass vowel is still too dark on the pickup.",
    confidence: 0.82,
    uncertaintyReasons: [
      "Synthetic demo data; use only to review the interface.",
      "Speaker labels are intentionally generic.",
    ],
    verificationStatus,
    evidence: [
      {
        id: `${id}-coach-feedback`,
        role: "COACH_FEEDBACK",
        label: "Coach gives the vowel reset instruction",
        startMs,
        endMs: startMs + 9_000,
      },
      {
        id: `${id}-after-attempt`,
        role: "AFTER_ATTEMPT",
        label: "Quartet repeats the passage after the adjustment",
        startMs: startMs + 28_000,
        endMs: startMs + 39_000,
      },
    ],
    ...overrides,
  };
}

function reviewInterventions(status: VerificationStatus): CoachingIntervention[] {
  return [
    makeIntervention(
      "synthetic-vowel-match",
      "Match vowels before the final chord",
      status,
      74_000,
    ),
    makeIntervention(
      "synthetic-breath-plan",
      "Plan the breath before the phrase peak",
      status,
      132_000,
      {
        exactCoachFeedback:
          "Synthetic demo coaching: take the shared breath earlier, then sing through the peak instead of breathing at it.",
        interpretation:
          "The breath needs to be part of the phrase plan so the high point keeps moving.",
        appliesTo: "Tenor and lead first, then the full quartet",
        songReference: "Demo uptune, second A section",
        problemBefore:
          "The phrase lost energy just before the highest note.",
        exerciseOrRequestedChange:
          "Mark the breath, breathe together one beat earlier, and carry the consonant forward.",
        observedResult:
          "The repeated pass kept tempo and sounded less effortful.",
        nextAction:
          "Lead: cue the earlier breath in the next rehearsal run.",
        unresolvedQuestion: null,
        confidence: 0.76,
      },
    ),
    makeIntervention(
      "synthetic-bass-balance",
      "Keep the bass line supportive, not dominant",
      status === "VERIFIED" ? "REJECTED" : status,
      211_000,
      {
        exactCoachFeedback:
          "Synthetic demo coaching: let the bass energize the chord without covering the inner parts.",
        interpretation:
          "The balance should let baritone and lead color be heard inside the chord.",
        appliesTo: "Bass, with full-quartet balance check",
        songReference: "Demo ballad, bridge resolution",
        problemBefore:
          "The bass resonance pulled attention away from the matched upper voices.",
        exerciseOrRequestedChange:
          "Bass sings mezzo-forte while the others keep their planned dynamic.",
        observedResult:
          "The chord still had foundation, and the inner harmony was easier to hear.",
        nextAction:
          "Bass: record one balance check at rehearsal tempo.",
        unresolvedQuestion:
          "Decide whether this is a balance issue or a vowel mismatch in the baritone.",
        confidence: 0.68,
      },
    ),
  ];
}

function seedSession(state: SessionState): SessionDetail {
  const hasLedger = state === "AWAITING_REVIEW" || state === "COMPLETE";
  const reviewed = state === "COMPLETE";
  const interventions = hasLedger
    ? reviewInterventions(reviewed ? "VERIFIED" : "UNVERIFIED")
    : [];
  const progressByState: Partial<Record<SessionState, number | null>> = {
    CREATED: 0,
    UPLOADING: 42,
    UPLOADED: 100,
    TRANSCRIBING: 38,
    RECONCILING: 63,
    TRANSCRIPT_READY: 72,
    EXTRACTING: 86,
    RETRY_PENDING: 58,
    DELETE_PENDING: 96,
  };
  const titleByState: Partial<Record<SessionState, string>> = {
    CREATED: "Synthetic demo upload created",
    UPLOADING: "Synthetic demo upload in progress",
    UPLOADED: "Synthetic demo upload waiting for transcription",
    TRANSCRIBING: "Synthetic demo transcription in progress",
    RECONCILING: "Synthetic demo transcript reconciliation",
    TRANSCRIPT_READY: "Synthetic demo transcript ready",
    EXTRACTING: "Synthetic demo coaching note extraction",
    AWAITING_REVIEW: "Synthetic demo awaiting review",
    COMPLETE: "Synthetic demo completed review",
    RETRY_PENDING: "Synthetic demo retry pending",
    FAILED: "Synthetic demo failed recording",
    CANCELLED: "Synthetic demo cancelled recording",
    DELETE_PENDING: "Synthetic demo deletion pending",
    DELETED: "Synthetic demo deleted recording",
  };

  return {
    id: `synthetic-${state.toLowerCase().replaceAll("_", "-")}`,
    title: titleByState[state] ?? "Synthetic demo recording",
    originalFileName: `synthetic-${state.toLowerCase().replaceAll("_", "-")}.wav`,
    createdAt: fixedNow,
    updatedAt: fixedNow,
    state,
    progress: progressByState[state] ?? (hasLedger ? 100 : null),
    error:
      state === "FAILED"
        ? {
            code: "SYNTHETIC_TRANSCRIPTION_ERROR",
            message:
              "Synthetic demo failure: the recording could not be transcribed because the file was unreadable.",
            retryable: true,
          }
        : null,
    durationMs: hasLedger ? 286_000 : state === "FAILED" ? 64_000 : null,
    interventionCount: interventions.length,
    reviewedInterventionCount: reviewed ? interventions.length : 0,
    audioUrl: hasLedger ? silentAudio : null,
    audioMimeType: hasLedger ? "audio/wav" : null,
    speakrSessionUrl: null,
    interventions,
  };
}

function defaultSessions(): SessionDetail[] {
  return [
    seedSession("COMPLETE"),
    seedSession("AWAITING_REVIEW"),
    seedSession("EXTRACTING"),
    seedSession("TRANSCRIBING"),
    seedSession("FAILED"),
  ];
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function summary(session: SessionDetail): SessionSummary {
  const {
    interventions: _interventions,
    audioUrl: _audioUrl,
    audioMimeType: _audioMimeType,
    speakrSessionUrl: _speakrSessionUrl,
    ...rest
  } = session;
  return rest;
}

function overviewFor(session: SessionDetail): SessionOverview | null {
  if (session.interventions.length === 0) return null;
  const themes = session.interventions.map((intervention, index) => {
    const starts = intervention.evidence.map((link) => link.startMs);
    const ends = intervention.evidence.map((link) => link.endMs ?? link.startMs);
    return {
      rank: index + 1,
      title: intervention.topic ?? "Coaching focus",
      summary:
        intervention.interpretation ??
        intervention.exactCoachFeedback ??
        "The coach worked on this synthetic passage.",
      interventionIds: [intervention.id],
      moments: [
        {
          interventionId: intervention.id,
          startMs: starts.length ? Math.min(...starts) : 0,
          endMs: ends.length ? Math.max(...ends) : 0,
        },
      ],
      startMs: starts.length ? Math.min(...starts) : 0,
      endMs: ends.length ? Math.max(...ends) : 0,
    };
  });
  return {
    id: `${session.id}-overview`,
    themes,
    interventionCount: session.interventions.length,
    stale: false,
    generatedAt: fixedGeneratedAt,
  };
}

export function createMockEvidenceApiClient(): EvidenceApiClient {
  const sessions = new Map<string, SessionDetail>();
  const requestedState = requestedMockState();
  let uploadCounter = 1;

  if (requestedState === null) {
    for (const session of defaultSessions()) sessions.set(session.id, session);
  } else if (requestedState !== "EMPTY" && requestedState !== "UPLOAD_PROGRESS") {
    const session = seedSession(requestedState);
    sessions.set(session.id, session);
  }

  const find = (id: string): SessionDetail => {
    const session = sessions.get(id);
    if (!session) throw new Error("Synthetic session not found.");
    return session;
  };

  return {
    async getCurrentUser() {
      return {
        username: "demo-singer",
      };
    },

    async listSessions() {
      return [...sessions.values()]
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt) || a.id.localeCompare(b.id))
        .map((session) => clone(summary(session)));
    },

    async getSession(id) {
      return clone(find(id));
    },

    async initiateUpload(request: UploadRequest): Promise<UploadTicket> {
      const id = `synthetic-upload-${uploadCounter.toString().padStart(2, "0")}`;
      uploadCounter += 1;
      const session: SessionDetail = {
        id,
        title: request.title?.trim() || request.fileName,
        originalFileName: request.fileName,
        createdAt: fixedUploadCreatedAt,
        updatedAt: fixedUploadCreatedAt,
        state: "UPLOADING",
        progress: 0,
        error: null,
        durationMs: null,
        interventionCount: 0,
        reviewedInterventionCount: 0,
        audioUrl: null,
        audioMimeType: null,
        speakrSessionUrl: null,
        interventions: [],
      };
      sessions.set(id, session);
      return {
        session: clone(summary(session)),
        upload: { id: "synthetic-upload", url: "mock://upload", method: "PUT" },
      };
    },

    async uploadFile(
      _target: UploadTarget,
      _file: File,
      onProgress: (progress: number) => void,
      signal?: AbortSignal,
    ) {
      for (const progress of [15, 38, 64, 86, 100]) {
        if (signal?.aborted) throw new DOMException("Upload cancelled", "AbortError");
        await new Promise((resolve) => setTimeout(resolve, 80));
        onProgress(progress);
      }
    },

    async completeUpload(sessionId) {
      const session = find(sessionId);
      session.state = "UPLOADED";
      session.progress = 100;
      session.updatedAt = fixedUploadCreatedAt;
      return clone(session);
    },

    async refreshFromSpeakr(sessionId) {
      const session = find(sessionId);
      const next: Partial<Record<SessionState, SessionState>> = {
        UPLOADED: "TRANSCRIBING",
        TRANSCRIBING: "TRANSCRIPT_READY",
        TRANSCRIPT_READY: "EXTRACTING",
        EXTRACTING: "AWAITING_REVIEW",
      };
      session.state = next[session.state] ?? session.state;
      session.updatedAt = fixedNow;
      return clone(session);
    },

    async reviewIntervention(
      sessionId,
      interventionId,
      review: InterventionReview,
    ): Promise<SessionDetail> {
      const session = find(sessionId);
      const intervention = session.interventions.find(
        (candidate) => candidate.id === interventionId,
      );
      if (!intervention) throw new Error("Synthetic intervention not found.");
      intervention.verificationStatus = review.verificationStatus;
      session.reviewedInterventionCount = session.interventions.filter(
        (item) =>
          item.verificationStatus === "VERIFIED" ||
          item.verificationStatus === "REJECTED",
      ).length;
      if (
        session.interventionCount > 0 &&
        session.reviewedInterventionCount === session.interventionCount
      ) {
        session.state = "COMPLETE";
      }
      session.updatedAt = fixedNow;
      return clone(session);
    },

    async cancelSession(sessionId) {
      const session = find(sessionId);
      session.state = "CANCELLED";
      session.updatedAt = fixedNow;
      return clone(session);
    },

    async deleteSession(sessionId) {
      sessions.delete(sessionId);
    },

    async getOverview(sessionId) {
      return clone(overviewFor(find(sessionId)));
    },

    async regenerateOverview() {
      // The synthetic client regenerates on read, so this is a no-op.
    },
  };
}
