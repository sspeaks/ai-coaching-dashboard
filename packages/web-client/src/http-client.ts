import type {
  CoachingIntervention,
  CurrentUser,
  EvidenceApiLedgerEntry,
  EvidenceApiClient,
  EvidenceApiSession,
  EvidenceApiSessionSummary,
  SessionDetail,
  SessionOverview,
  SessionSummary,
  UploadRequest,
  UploadTarget,
  UploadTicket,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface HttpClientOptions {
  baseUrl?: string;
  fetch?: typeof globalThis.fetch;
}

function joinUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}

async function parseResponse(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) return response.json();
  const text = await response.text();
  return text || undefined;
}

function errorMessage(status: number, body: unknown): string {
  if (status === 401) return "Your session has expired. Sign in again.";
  if (status === 403) return "You do not have access to this recording.";
  if (body && typeof body === "object") {
    if ("message" in body) {
      const message = (body as { message?: unknown }).message;
      if (typeof message === "string") return message;
    }
    if ("detail" in body) {
      const detail = (body as { detail?: unknown }).detail;
      if (detail && typeof detail === "object" && "message" in detail) {
        const message = (detail as { message?: unknown }).message;
        if (typeof message === "string") return message;
      }
    }
  }
  return `The evidence service returned ${status}.`;
}

export function createHttpEvidenceApiClient(
  options: HttpClientOptions = {},
): EvidenceApiClient {
  const baseUrl = options.baseUrl ?? "/api";
  const fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);

  async function request<T>(
    path: string,
    init: RequestInit = {},
  ): Promise<T> {
    const response = await fetcher(joinUrl(baseUrl, path), {
      ...init,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
    const body = await parseResponse(response);
    if (!response.ok) {
      throw new ApiError(errorMessage(response.status, body), response.status, body);
    }
    return body as T;
  }

  async function getSession(
    id: string,
    signal?: AbortSignal,
  ): Promise<SessionDetail> {
    const encodedId = encodeURIComponent(id);
    const [session, ledger] = await Promise.all([
      request<EvidenceApiSession>(`/sessions/${encodedId}`, { signal }),
      request<EvidenceApiLedgerEntry[]>(`/sessions/${encodedId}/ledger`, {
        signal,
      }),
    ]);
    return mapSessionDetail(session, ledger);
  }

  return {
    getCurrentUser: (signal) => request<CurrentUser>("/me", { signal }),

    listSessions: async (signal) =>
      (
        await request<EvidenceApiSession[]>("/sessions", { signal })
      ).map(mapSessionSummary),

    getSession,

    initiateUpload: async (uploadRequest: UploadRequest): Promise<UploadTicket> => {
      const session = await request<EvidenceApiSession>("/sessions", {
        method: "POST",
        body: JSON.stringify({
          title: uploadRequest.title?.trim() || uploadRequest.fileName,
        }),
      });
      return {
        session: mapSessionSummary(session),
        upload: {
          url: joinUrl(
            baseUrl,
            `/sessions/${encodeURIComponent(session.id)}/media`,
          ),
          method: "POST",
          fileFieldName: "media",
        },
      };
    },

    uploadFile: (target, file, onProgress, signal) =>
      uploadWithProgress(target, file, onProgress, signal),

    completeUpload: (sessionId, _uploadId) => getSession(sessionId),

    refreshFromSpeakr: async (sessionId) => {
      await request<EvidenceApiSession>(
        `/sessions/${encodeURIComponent(sessionId)}/refresh`,
        { method: "POST", body: "{}" },
      );
      return getSession(sessionId);
    },

    reviewIntervention: async (sessionId, interventionId, review) => {
      await request<EvidenceApiLedgerEntry>(
        `/ledger/${encodeURIComponent(interventionId)}/verification`,
        {
          method: "PUT",
          body: JSON.stringify({
            status: review.verificationStatus,
            note: review.note ?? null,
          }),
        },
      );
      return getSession(sessionId);
    },

    getOverview: async (sessionId, signal) => {
      try {
        const body = await request<EvidenceApiSessionSummary>(
          `/sessions/${encodeURIComponent(sessionId)}/summary`,
          { signal },
        );
        return {
          id: body.id,
          interventionCount: body.entry_count,
          stale: body.stale,
          generatedAt: body.generated_at,
          themes: body.themes.map((theme) => ({
            rank: theme.rank,
            title: theme.title,
            summary: theme.summary,
            interventionIds: theme.ledger_entry_ids,
            moments: theme.moments.map((moment) => ({
              interventionId: moment.ledger_entry_id,
              startMs: moment.start_ms,
              endMs: moment.end_ms,
            })),
            startMs: theme.start_ms,
            endMs: theme.end_ms,
          })),
        };
      } catch (caught) {
        // A session with no overview yet is an ordinary state, not an error.
        if (caught instanceof ApiError && caught.status === 404) return null;
        throw caught;
      }
    },

    regenerateOverview: async (sessionId) => {
      await request<unknown>(`/sessions/${encodeURIComponent(sessionId)}/jobs`, {
        method: "POST",
        body: JSON.stringify({ type: "SUMMARIZE" }),
      });
    },

    cancelSession: async (sessionId) => {
      await request<EvidenceApiSession>(
        `/sessions/${encodeURIComponent(sessionId)}/cancel`,
        {
          method: "POST",
          body: "{}",
        },
      );
      return getSession(sessionId);
    },

    deleteSession: async (sessionId) => {
      await request<EvidenceApiSession>(`/sessions/${encodeURIComponent(sessionId)}`, {
        method: "DELETE",
      });
      await request<void>(
        `/sessions/${encodeURIComponent(sessionId)}/deletion/confirm`,
        {
          method: "POST",
          body: JSON.stringify({ confirm_session_id: sessionId }),
        },
      );
    },
  };
}

function mapSessionSummary(session: EvidenceApiSession): SessionSummary {
  return {
    id: session.id,
    title: session.title,
    originalFileName: session.original_filename || "Recording",
    createdAt: session.created_at,
    updatedAt: session.updated_at,
    state: session.state,
    progress: progressForState(session.state),
    error: session.last_error
      ? {
          message: session.last_error,
          retryable: session.state === "RETRY_PENDING",
        }
      : null,
    durationMs: session.duration_ms,
    interventionCount: session.ledger_entry_count,
    reviewedInterventionCount: session.reviewed_ledger_entry_count,
  };
}

function mapSessionDetail(
  session: EvidenceApiSession,
  ledger: EvidenceApiLedgerEntry[],
): SessionDetail {
  return {
    ...mapSessionSummary(session),
    audioUrl: session.playback_url,
    audioMimeType: null,
    speakrSessionUrl: null,
    interventions: ledger.map(mapLedgerEntry),
  };
}

function mapLedgerEntry(entry: EvidenceApiLedgerEntry): CoachingIntervention {
  const uncertainty = entry.extraction_metadata.uncertainty_reasons;
  return {
    id: entry.id,
    topic: entry.topic,
    exactCoachFeedback: entry.exact_coach_feedback,
    interpretation: entry.interpretation,
    appliesTo: entry.applies_to,
    songReference: entry.song_passage_measure,
    problemBefore: entry.problem_heard_before,
    exerciseOrRequestedChange: entry.exercise_or_requested_change,
    observedResult: entry.observed_result,
    nextAction: entry.next_action_and_owner,
    unresolvedQuestion: entry.unresolved_question,
    confidence: entry.confidence,
    uncertaintyReasons: Array.isArray(uncertainty)
      ? uncertainty.filter((item): item is string => typeof item === "string")
      : [],
    verificationStatus: entry.verification_status,
    evidence: entry.evidence.map((evidence, index) => ({
      id: `${entry.id}:${index}`,
      role: "COACH_FEEDBACK",
      label: `Transcript segments ${evidence.segment_ids.join(", ")}`,
      startMs: evidence.start_ms,
      endMs: evidence.end_ms,
    })),
  };
}

function progressForState(state: EvidenceApiSession["state"]): number {
  const progress: Record<string, number> = {
    CREATED: 0,
    UPLOADING: 10,
    UPLOADED: 20,
    TRANSCRIBING: 45,
    RECONCILING: 60,
    TRANSCRIPT_READY: 65,
    EXTRACTING: 80,
    AWAITING_REVIEW: 100,
    COMPLETE: 100,
    RETRY_PENDING: 45,
    FAILED: 100,
    CANCELLED: 100,
    DELETE_PENDING: 100,
    DELETED: 100,
  };
  return progress[state] ?? 0;
}

function uploadWithProgress(
  target: UploadTarget,
  file: File,
  onProgress: (progress: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const isMultipart = Boolean(target.formFields || target.fileFieldName);
    const method = target.method ?? (isMultipart ? "POST" : "PUT");
    xhr.open(method, target.url);

    if (typeof window !== "undefined") {
      const uploadOrigin = new URL(target.url, window.location.href).origin;
      xhr.withCredentials = uploadOrigin === window.location.origin;
    }

    Object.entries(target.headers ?? {}).forEach(([name, value]) => {
      xhr.setRequestHeader(name, value);
    });
    if (!isMultipart && !target.headers?.["Content-Type"] && file.type) {
      xhr.setRequestHeader("Content-Type", file.type);
    }

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(100);
        resolve();
      } else {
        reject(new ApiError("The recording upload failed.", xhr.status));
      }
    });
    xhr.addEventListener("error", () => {
      reject(new ApiError("The recording upload could not reach storage.", 0));
    });
    xhr.addEventListener("abort", () => {
      reject(new DOMException("Upload cancelled", "AbortError"));
    });

    const abort = () => xhr.abort();
    signal?.addEventListener("abort", abort, { once: true });

    if (isMultipart) {
      const form = new FormData();
      Object.entries(target.formFields ?? {}).forEach(([name, value]) =>
        form.append(name, value),
      );
      form.append(target.fileFieldName ?? "file", file);
      xhr.send(form);
    } else {
      xhr.send(file);
    }
  });
}
