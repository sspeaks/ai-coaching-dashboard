import type {
  EvidenceApiClient,
  InterventionReview,
  SessionDetail,
  SessionState,
  SessionSummary,
  UploadRequest,
  UploadTarget,
  UploadTicket,
} from "./types";

const silentAudio =
  "data:audio/wav;base64,UklGRiwAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQgAAACAgICAgICAgA==";

const now = new Date().toISOString();

function seedSession(): SessionDetail {
  return {
    id: "synthetic-review-session",
    title: "Synthetic review example",
    originalFileName: "interface-demo.wav",
    createdAt: now,
    updatedAt: now,
    state: "AWAITING_REVIEW",
    progress: 100,
    durationMs: 180_000,
    interventionCount: 1,
    reviewedInterventionCount: 0,
    audioUrl: silentAudio,
    audioMimeType: "audio/wav",
    speakrSessionUrl: null,
    interventions: [
      {
        id: "synthetic-intervention",
        topic: "Interface demonstration",
        exactCoachFeedback: "Synthetic coaching note for interface demonstration only.",
        interpretation: null,
        appliesTo: null,
        songReference: null,
        problemBefore: null,
        exerciseOrRequestedChange: "Review the linked source before accepting this entry.",
        observedResult: null,
        nextAction: null,
        unresolvedQuestion: "This is not a real coaching conclusion.",
        confidence: 0.52,
        uncertaintyReasons: [
          "Synthetic data mode is enabled.",
          "No musical outcome is asserted.",
        ],
        verificationStatus: "UNVERIFIED",
        evidence: [
          {
            id: "synthetic-evidence",
            role: "COACH_FEEDBACK",
            label: "Synthetic evidence link",
            startMs: 0,
            endMs: 1_000,
          },
        ],
      },
    ],
  };
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

export function createMockEvidenceApiClient(): EvidenceApiClient {
  const sessions = new Map<string, SessionDetail>();
  const seeded = seedSession();
  sessions.set(seeded.id, seeded);

  const find = (id: string): SessionDetail => {
    const session = sessions.get(id);
    if (!session) throw new Error("Synthetic session not found.");
    return session;
  };

  return {
    async listSessions() {
      return [...sessions.values()]
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
        .map((session) => clone(summary(session)));
    },

    async getSession(id) {
      return clone(find(id));
    },

    async initiateUpload(request: UploadRequest): Promise<UploadTicket> {
      const id = `synthetic-${Date.now()}`;
      const session: SessionDetail = {
        id,
        title: request.title?.trim() || request.fileName,
        originalFileName: request.fileName,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        state: "UPLOADING",
        progress: 0,
        durationMs: null,
        interventionCount: 0,
        reviewedInterventionCount: 0,
        audioUrl: null,
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
      session.updatedAt = new Date().toISOString();
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
      session.updatedAt = new Date().toISOString();
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
      return clone(session);
    },

    async cancelSession(sessionId) {
      const session = find(sessionId);
      session.state = "CANCELLED";
      session.updatedAt = new Date().toISOString();
      return clone(session);
    },

    async deleteSession(sessionId) {
      sessions.delete(sessionId);
    },

    async getOverview(sessionId) {
      const session = find(sessionId);
      if (session.interventions.length === 0) return null;
      const themes = session.interventions.slice(0, 5).map((intervention, index) => {
        const starts = intervention.evidence.map((link) => link.startMs);
        const ends = intervention.evidence.map((link) => link.endMs ?? link.startMs);
        return {
          rank: index + 1,
          title: intervention.topic ?? "Coaching focus",
          summary:
            intervention.interpretation ??
            intervention.exactCoachFeedback ??
            "The coach worked on this passage.",
          interventionIds: [intervention.id],
          startMs: starts.length ? Math.min(...starts) : 0,
          endMs: ends.length ? Math.max(...ends) : 0,
        };
      });
      return {
        id: `${session.id}-overview`,
        themes,
        interventionCount: session.interventions.length,
        stale: false,
        generatedAt: new Date().toISOString(),
      };
    },

    async regenerateOverview() {
      // The synthetic client regenerates on read, so this is a no-op.
    },
  };
}
