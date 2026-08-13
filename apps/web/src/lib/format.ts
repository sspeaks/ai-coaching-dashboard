import {
  isFailedSessionState,
  type EvidenceRole,
  type SessionState,
} from "@quartet-coach/web-client";

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatTimestampMs(milliseconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const remainder = safeSeconds % 60;
  return hours > 0
    ? `${hours}:${minutes.toString().padStart(2, "0")}:${remainder
        .toString()
        .padStart(2, "0")}`
    : `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

export type StatusTone = "ready" | "working" | "problem" | "neutral";

export interface SessionStatus {
  label: string;
  tone: StatusTone;
  /** One sentence a singer can act on, or null when the label says enough. */
  detail: string | null;
  /** Optional operator-facing pipeline detail; never the primary status. */
  technicalDetail: string | null;
}

/**
 * Singers never see the processing state machine. They see where their
 * recording is in plain words, and whether anything is expected of them.
 */
export function sessionStatus(state: SessionState): SessionStatus {
  if (isFailedSessionState(state)) {
    return {
      label: "Needs help",
      tone: "problem",
      detail: "This recording could not be turned into coaching notes.",
      technicalDetail: `Technical status: ${state}`,
    };
  }
  switch (state) {
    case "CREATED":
    case "UPLOADING":
    case "UPLOADED":
      return {
        label: "Uploading",
        tone: "working",
        detail: null,
        technicalDetail: `Technical status: ${state}`,
      };
    case "TRANSCRIBING":
      return {
        label: "Listening to the recording",
        tone: "working",
        detail: "This usually takes a few minutes for a full rehearsal.",
        technicalDetail: "Technical status: transcription is in progress.",
      };
    case "RECONCILING":
    case "TRANSCRIPT_READY":
    case "EXTRACTING":
    case "RETRY_PENDING":
      return {
        label: "Writing coaching notes",
        tone: "working",
        detail: "The notes are being prepared from the recording.",
        technicalDetail: `Technical status: ${state}`,
      };
    case "AWAITING_REVIEW":
    case "COMPLETE":
      return {
        label: "Ready to read",
        tone: "ready",
        detail: null,
        technicalDetail: `Technical status: ${state}`,
      };
    case "CANCELLED":
      return {
        label: "Cancelled",
        tone: "neutral",
        detail: null,
        technicalDetail: `Technical status: ${state}`,
      };
    case "DELETE_PENDING":
    case "DELETED":
      return {
        label: "Deleting",
        tone: "neutral",
        detail: null,
        technicalDetail: `Technical status: ${state}`,
      };
    default:
      return {
        label: "Getting this ready",
        tone: "working",
        detail: null,
        technicalDetail: `Technical status: ${state}`,
      };
  }
}

export function evidenceRoleLabel(role: EvidenceRole): string {
  const labels: Record<EvidenceRole, string> = {
    COACH_FEEDBACK: "Coach feedback",
    BEFORE_PERFORMANCE: "Before",
    AFTER_ATTEMPT: "After attempt",
    OTHER: "Other evidence",
  };
  return labels[role];
}
