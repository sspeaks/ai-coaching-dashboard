import { useRef, useState } from "react";
import {
  isActiveSessionState,
  isFailedSessionState,
  type EvidenceApiClient,
  type SessionDetail as SessionDetailType,
} from "@quartet-coach/web-client";
import { formatDate, sessionStatus } from "../lib/format";
import { LedgerReview } from "./LedgerReview";
import { SessionOverviewPanel } from "./SessionOverviewPanel";
import { StatusBadge } from "./StatusBadge";

interface AudioMoment {
  key: string;
  label: string;
  noteTitle: string;
}

interface SessionDetailProps {
  session: SessionDetailType;
  client: EvidenceApiClient;
  onChanged: (session: SessionDetailType) => void;
  onDeleted: (sessionId: string) => void;
  onUploadDifferent?: () => void;
  showRecordingOptions?: boolean;
}

export function SessionDetail({
  session,
  client,
  onChanged,
  onDeleted,
  onUploadDifferent,
  showRecordingOptions = false,
}: SessionDetailProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeMoment, setActiveMoment] = useState<AudioMoment | null>(null);
  // The summary is the landing view: the full ledger is far too dense to be
  // the first thing a singer sees after a rehearsal.
  const [view, setView] = useState<"summary" | "ledger">("summary");

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
        "Delete this recording and its coaching notes? This cannot be undone.",
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

  function seek(seconds: number, moment: AudioMoment) {
    setActiveMoment(moment);
    if (!audioRef.current) return;
    audioRef.current.currentTime = seconds;
    audioRef.current.focus();
    void audioRef.current.play().catch(() => {
      // Browser autoplay policy may require the user to press play.
    });
  }

  const canCancel =
    isActiveSessionState(session.state) && session.state !== "DELETE_PENDING";
  const status = sessionStatus(session.state);
  const readyForFeedback = status.tone === "ready";
  const failed = session.error || isFailedSessionState(session.state);

  return (
    <section className="panel detail-panel" aria-labelledby="detail-heading">
      <div className="detail-header">
        <div>
          <p className="eyebrow">Recording</p>
          <h2 id="detail-heading">{session.title}</h2>
          <p className="detail-subtitle">
            {session.originalFileName} · Added {formatDate(session.createdAt)}
          </p>
        </div>
        <StatusBadge state={session.state} />
      </div>

      {!readyForFeedback && (
        <div className={`status-callout status-callout--${status.tone}`} role="status">
          <strong>{status.label}</strong>
          <p>
            {status.detail ?? "We will show the coaching notes here when the recording is ready."}
          </p>
          {session.progress != null &&
            session.progress < 100 &&
            isActiveSessionState(session.state) && (
              <div className="processing-progress" aria-live="polite">
                <div className="progress-row">
                  <span>Progress</span>
                  <strong>{session.progress}%</strong>
                </div>
                <progress value={session.progress} max="100" />
              </div>
            )}
        </div>
      )}

      {showRecordingOptions && (
        <details className="advanced-panel">
          <summary>Recording options</summary>
          <div className="session-actions">
            <button
              className="button button--secondary"
              onClick={() =>
                runAction("refresh", () => client.refreshFromSpeakr(session.id))
              }
              disabled={action !== null}
            >
              {action === "refresh" ? "Checking…" : "Check for transcript updates"}
            </button>
            {session.speakrSessionUrl && (
              <a
                className="button button--quiet"
                href={session.speakrSessionUrl}
                target="_blank"
                rel="noreferrer"
              >
                Open transcript editor
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
                {action === "cancel" ? "Cancelling…" : "Cancel"}
              </button>
            )}
            <button
              className="button button--danger"
              onClick={deleteSession}
              disabled={action !== null}
            >
              {action === "delete" ? "Deleting…" : "Delete recording"}
            </button>
          </div>
        </details>
      )}

      {failed && (
        <div
          className="recovery-panel"
          role="alert"
          aria-labelledby={`recovery-${session.id}`}
        >
          <p className="eyebrow">Needs action</p>
          <h3 id={`recovery-${session.id}`}>This file could not be read.</h3>
          <p>
            Upload a different MP3, WAV, or M4A file. If the new file also
            fails, ask an admin for help.
          </p>
          {session.error?.message && (
            <p className="recovery-panel__detail">{session.error.message}</p>
          )}
          <div className="page-actions">
            {onUploadDifferent ? (
              <button className="button button--primary" onClick={onUploadDifferent}>
                Upload a different file
              </button>
            ) : (
              <a className="button button--primary" href="/upload">
                Upload a different file
              </a>
            )}
            <button
              className="button button--secondary"
              onClick={() =>
                runAction("refresh", () => client.refreshFromSpeakr(session.id))
              }
              disabled={action !== null}
            >
              {action === "refresh" ? "Checking…" : "Check again"}
            </button>
          </div>
        </div>
      )}
      {error && (
        <div className="inline-alert inline-alert--danger" role="alert">
          {error}
        </div>
      )}

      <div
        className={`audio-section${activeMoment ? " audio-section--active" : ""}`}
        aria-live="polite"
      >
        <div>
          <p className="eyebrow">Source recording</p>
          {activeMoment ? (
            <p className="audio-section__now">
              Playing from {activeMoment.label} for “{activeMoment.noteTitle}”
            </p>
          ) : (
            <p className="audio-section__hint">
              Use any “▶ Play…” button in the notes to jump here.
            </p>
          )}
        </div>
        {session.audioUrl ? (
          <audio ref={audioRef} controls preload="metadata" src={session.audioUrl}>
            Your browser does not support audio playback.
          </audio>
        ) : (
          <p className="missing-value">
            The recording will be playable here after upload processing finishes.
          </p>
        )}
      </div>

      {!readyForFeedback && !isFailedSessionState(session.state) ? (
        <div className="empty-state feedback-waiting">
          <h3>Coaching notes are not ready yet</h3>
          <p>
            You can leave and come back later. This page will update while the
            recording is being prepared.
          </p>
        </div>
      ) : view === "summary" ? (
        <SessionOverviewPanel
          session={session}
          client={client}
          onSeek={seek}
          activeMomentKey={activeMoment?.key ?? null}
          audioAvailable={Boolean(session.audioUrl)}
          onShowAll={() => setView("ledger")}
        />
      ) : (
        <>
          <div className="ledger-heading">
            <div>
              <p className="eyebrow">Every note</p>
              <h3>All timestamped coaching notes</h3>
            </div>
            <strong>
              {session.interventionCount} notes
            </strong>
          </div>
          <button
            className="button button--quiet"
            onClick={() => setView("summary")}
          >
            Back to main points
          </button>
          <LedgerReview
            session={session}
            client={client}
            onSeek={seek}
            activeMomentKey={activeMoment?.key ?? null}
            audioAvailable={Boolean(session.audioUrl)}
            onUpdated={onChanged}
          />
        </>
      )}
    </section>
  );
}
