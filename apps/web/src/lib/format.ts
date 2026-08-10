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
}

/**
 * Singers never see the processing state machine. They see where their
 * recording is in plain words, and whether anything is expected of them.
 */
export function sessionStatus(state: SessionState): SessionStatus {
  if (isFailedSessionState(state)) {
    return {
      label: "Something went wrong",
      tone: "problem",
      detail: "This recording could not be turned into coaching notes.",
    };
  }
  switch (state) {
    case "CREATED":
    case "UPLOADING":
    case "UPLOADED":
      return { label: "Uploading", tone: "working", detail: null };
    case "TRANSCRIBING":
    case "RECONCILING":
    case "TRANSCRIPT_READY":
      return {
        label: "Listening to the recording",
        tone: "working",
        detail: "This usually takes a few minutes for a full rehearsal.",
      };
    case "EXTRACTING":
      return {
        label: "Writing up the coaching notes",
        tone: "working",
        detail: "Almost there — the notes are being pulled out of the recording.",
      };
    case "AWAITING_REVIEW":
    case "COMPLETE":
      return { label: "Ready", tone: "ready", detail: null };
    case "RETRY_PENDING":
      return { label: "Trying again", tone: "working", detail: null };
    case "CANCELLED":
      return { label: "Cancelled", tone: "neutral", detail: null };
    case "DELETE_PENDING":
    case "DELETED":
      return { label: "Deleting", tone: "neutral", detail: null };
    default:
      return { label: "Working on it", tone: "working", detail: null };
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
