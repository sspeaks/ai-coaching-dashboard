import { useRef, useState } from "react";
import {
  isActiveSessionState,
  isFailedSessionState,
  type EvidenceApiClient,
  type SessionDetail as SessionDetailType,
} from "@quartet-coach/web-client";
import { formatDate } from "../lib/format";
import { LedgerReview } from "./LedgerReview";
import { StatusBadge } from "./StatusBadge";

interface SessionDetailProps {
  session: SessionDetailType;
  client: EvidenceApiClient;
  onChanged: (session: SessionDetailType) => void;
  onDeleted: (sessionId: string) => void;
}

export function SessionDetail({
  session,
  client,
  onChanged,
  onDeleted,
}: SessionDetailProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runAction(
    name: string,
    operation: () => Promise<SessionDetailType>,
  ) {
    setAction(name);
    setError(null);
    try {
      onChanged(await operation());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The action failed.");
    } finally {
      setAction(null);
    }
  }

  async function deleteSession() {
    if (
      !window.confirm(
        "Delete this session and its retained recording? This action cannot be undone.",
      )
    ) {
      return;
    }
    setAction("delete");
    setError(null);
    try {
      await client.deleteSession(session.id);
      onDeleted(session.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Delete failed.");
      setAction(null);
    }
  }

  function seek(seconds: number) {
    if (!audioRef.current) return;
    audioRef.current.currentTime = seconds;
    audioRef.current.focus();
    void audioRef.current.play().catch(() => {
      // Browser autoplay policy may require the user to press play.
    });
  }

  const canCancel =
    isActiveSessionState(session.state) && session.state !== "DELETE_PENDING";

  return (
    <section className="panel detail-panel" aria-labelledby="detail-heading">
      <div className="detail-header">
        <div>
          <p className="eyebrow">Session record</p>
          <h2 id="detail-heading">{session.title}</h2>
          <p className="detail-subtitle">
            {session.originalFileName} · Added {formatDate(session.createdAt)}
          </p>
        </div>
        <StatusBadge state={session.state} />
      </div>

      <div className="session-actions">
        <button
          className="button button--secondary"
          onClick={() =>
            runAction("refresh", () => client.refreshFromSpeakr(session.id))
          }
          disabled={action !== null}
        >
          {action === "refresh" ? "Refreshing…" : "Refresh from Speakr"}
        </button>
        {session.speakrSessionUrl && (
          <a
            className="button button--quiet"
            href={session.speakrSessionUrl}
            target="_blank"
            rel="noreferrer"
          >
            Open transcript in Speakr
          </a>
        )}
        {canCancel && (
          <button
            className="button button--quiet"
            onClick={() =>
              runAction("cancel", () => client.cancelSession(session.id))
            }
            disabled={action !== null}
          >
            {action === "cancel" ? "Cancelling…" : "Cancel processing"}
          </button>
        )}
        <button
          className="button button--danger"
          onClick={deleteSession}
          disabled={action !== null}
        >
          {action === "delete" ? "Deleting…" : "Delete session"}
        </button>
      </div>
      <p className="supporting-text">
        Refresh imports current processing and transcript-derived evidence from
        Speakr. Transcript editing remains in Speakr.
      </p>

      {session.progress != null &&
        session.progress < 100 &&
        isActiveSessionState(session.state) && (
          <div className="processing-progress" aria-live="polite">
            <div className="progress-row">
              <span>Current stage progress</span>
              <strong>{session.progress}%</strong>
            </div>
            <progress value={session.progress} max="100" />
          </div>
        )}

      {(session.error || isFailedSessionState(session.state)) && (
        <div className="inline-alert inline-alert--danger" role="alert">
          <strong>Processing stopped.</strong>{" "}
          {session.error?.message ||
            "The service did not provide a specific failure reason."}
          {session.error?.retryable && (
            <span> Refresh from Speakr after the source issue is resolved.</span>
          )}
        </div>
      )}
      {error && (
        <div className="inline-alert inline-alert--danger" role="alert">
          {error}
        </div>
      )}

      <div className="audio-section">
        <div>
          <p className="eyebrow">Source recording</p>
          <h3>Evidence playback</h3>
        </div>
        {session.audioUrl ? (
          <audio ref={audioRef} controls preload="metadata" src={session.audioUrl}>
            Your browser does not support audio playback.
          </audio>
        ) : (
          <p className="missing-value">
            Audio playback is not available for this session yet.
          </p>
        )}
      </div>

      <div className="ledger-heading">
        <div>
          <p className="eyebrow">Human-verified record</p>
          <h3>Coaching interventions</h3>
        </div>
        <strong>
          {session.reviewedInterventionCount}/{session.interventionCount} reviewed
        </strong>
      </div>
      <LedgerReview
        session={session}
        client={client}
        onSeek={seek}
        audioAvailable={Boolean(session.audioUrl)}
        onUpdated={onChanged}
      />
    </section>
  );
}
