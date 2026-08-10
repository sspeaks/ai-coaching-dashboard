export type KnownSessionState =
  | "CREATED"
  | "UPLOADING"
  | "UPLOADED"
  | "TRANSCRIBING"
  | "RECONCILING"
  | "TRANSCRIPT_READY"
  | "EXTRACTING"
  | "AWAITING_REVIEW"
  | "COMPLETE"
  | "RETRY_PENDING"
  | "FAILED"
  | "CANCELLED"
  | "DELETE_PENDING"
  | "DELETED";

export type SessionState = KnownSessionState | (string & {});

export type VerificationStatus =
  | "UNVERIFIED"
  | "VERIFIED"
  | "REJECTED"
  | "NEEDS_REVIEW";

export type EvidenceRole =
  | "COACH_FEEDBACK"
  | "BEFORE_PERFORMANCE"
  | "AFTER_ATTEMPT"
  | "OTHER";

export interface ProcessingError {
  code?: string;
  message: string;
  retryable?: boolean;
}

export interface EvidenceApiSession {
  id: string;
  title: string;
  state: SessionState;
  recorded_at: string | null;
  duration_ms: number | null;
  original_filename: string | null;
  media_sha256: string | null;
  speakr_recording_id: string | null;
  current_transcript_revision_id: string | null;
  last_reconciled_at: string | null;
  last_error: string | null;
  playback_url: string | null;
  ledger_entry_count: number;
  reviewed_ledger_entry_count: number;
  created_at: string;
  updated_at: string;
}

export interface EvidenceApiSummaryMoment {
  ledger_entry_id: string;
  start_ms: number;
  end_ms: number;
}

export interface EvidenceApiSummaryTheme {
  rank: number;
  title: string;
  summary: string;
  ledger_entry_ids: string[];
  moments: EvidenceApiSummaryMoment[];
  start_ms: number;
  end_ms: number;
}

export interface EvidenceApiSessionSummary {
  id: string;
  session_id: string;
  transcript_revision_id: string;
  themes: EvidenceApiSummaryTheme[];
  entry_count: number;
  stale: boolean;
  generated_at: string;
}

export interface CurrentUser {
  username: string;
}

export interface EvidenceApiReference {
  transcript_revision_id: string;
  start_ms: number;
  end_ms: number;
  segment_ids: string[];
}

export interface EvidenceApiLedgerEntry {
  id: string;
  session_id: string;
  transcript_revision_id: string;
  topic: string;
  exact_coach_feedback: string | null;
  interpretation: string | null;
  applies_to: string | null;
  song_passage_measure: string | null;
  problem_heard_before: string | null;
  exercise_or_requested_change: string | null;
  observed_result: string | null;
  next_action_and_owner: string | null;
  unresolved_question: string | null;
  confidence: number;
  evidence: EvidenceApiReference[];
  extraction_metadata: Record<string, unknown>;
  verification_status: VerificationStatus;
  verified_by: string | null;
  verified_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SessionSummary {
  id: string;
  title: string;
  originalFileName: string;
  createdAt: string;
  updatedAt: string;
  state: SessionState;
  progress?: number | null;
  error?: ProcessingError | null;
  durationMs?: number | null;
  interventionCount: number;
  reviewedInterventionCount: number;
}

export interface EvidenceLink {
  id: string;
  role: EvidenceRole;
  label: string;
  startMs: number;
  endMs?: number | null;
}

export interface CoachingIntervention {
  id: string;
  topic: string | null;
  exactCoachFeedback: string | null;
  interpretation: string | null;
  appliesTo: string | null;
  songReference: string | null;
  problemBefore: string | null;
  exerciseOrRequestedChange: string | null;
  observedResult: string | null;
  nextAction: string | null;
  unresolvedQuestion: string | null;
  confidence: number | null;
  uncertaintyReasons: string[];
  verificationStatus: VerificationStatus;
  evidence: EvidenceLink[];
}

export interface SessionMoment {
  interventionId: string;
  startMs: number;
  endMs: number;
}

export interface SessionTheme {
  rank: number;
  title: string;
  summary: string;
  interventionIds: string[];
  /** Each place in the recording this theme was worked on. */
  moments: SessionMoment[];
  startMs: number;
  endMs: number;
}

export interface SessionOverview {
  id: string;
  themes: SessionTheme[];
  interventionCount: number;
  /** The ledger changed after this overview was generated. */
  stale: boolean;
  generatedAt: string;
}

export interface SessionDetail extends SessionSummary {
  audioUrl?: string | null;
  audioMimeType?: string | null;
  speakrSessionUrl?: string | null;
  interventions: CoachingIntervention[];
}

export interface UploadRequest {
  fileName: string;
  contentType: string;
  sizeBytes: number;
  title?: string;
}

export interface UploadTarget {
  id?: string;
  url: string;
  method?: "PUT" | "POST";
  headers?: Record<string, string>;
  formFields?: Record<string, string>;
  fileFieldName?: string;
}

export interface UploadTicket {
  session: SessionSummary;
  upload: UploadTarget;
}

export interface InterventionReview {
  verificationStatus: "VERIFIED" | "REJECTED";
  note?: string | null;
}

export interface EvidenceApiClient {
  getCurrentUser(signal?: AbortSignal): Promise<CurrentUser>;
  listSessions(signal?: AbortSignal): Promise<SessionSummary[]>;
  getSession(id: string, signal?: AbortSignal): Promise<SessionDetail>;
  initiateUpload(request: UploadRequest): Promise<UploadTicket>;
  uploadFile(
    target: UploadTarget,
    file: File,
    onProgress: (progress: number) => void,
    signal?: AbortSignal,
  ): Promise<void>;
  completeUpload(sessionId: string, uploadId?: string): Promise<SessionDetail>;
  refreshFromSpeakr(sessionId: string): Promise<SessionDetail>;
  reviewIntervention(
    sessionId: string,
    interventionId: string,
    review: InterventionReview,
  ): Promise<SessionDetail>;
  cancelSession(sessionId: string): Promise<SessionDetail>;
  deleteSession(sessionId: string): Promise<void>;
  /** Resolves to null when the session has not been summarized yet. */
  getOverview(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<SessionOverview | null>;
  regenerateOverview(sessionId: string): Promise<void>;
}

export const activeSessionStates = new Set<SessionState>([
  "CREATED",
  "UPLOADING",
  "UPLOADED",
  "TRANSCRIBING",
  "RECONCILING",
  "TRANSCRIPT_READY",
  "EXTRACTING",
  "RETRY_PENDING",
  "DELETE_PENDING",
]);

export const failedSessionStates = new Set<SessionState>(["FAILED"]);

export function isActiveSessionState(state: SessionState): boolean {
  return activeSessionStates.has(state);
}

export function isFailedSessionState(state: SessionState): boolean {
  return failedSessionStates.has(state) || state.endsWith("_FAILED");
}
