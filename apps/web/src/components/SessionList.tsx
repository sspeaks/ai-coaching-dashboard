import type { SessionSummary } from "@quartet-coach/web-client";
import { formatDate, sessionStatus } from "../lib/format";
import { StatusBadge } from "./StatusBadge";

interface SessionListProps {
  sessions: SessionSummary[];
  loading: boolean;
  selectedId?: string | null;
  detailId: string;
  onOpen: (id: string) => void;
  onRefresh: () => void;
}

export function SessionList({
  sessions,
  loading,
  selectedId = null,
  detailId,
  onOpen,
  onRefresh,
}: SessionListProps) {
  return (
    <section
      className="panel session-list-panel"
      aria-labelledby="sessions-heading"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Your recordings</p>
          <h2 id="sessions-heading">Choose a coaching recording</h2>
        </div>
        <button
          className="button button--quiet button--compact"
          onClick={onRefresh}
          disabled={loading}
        >
          {loading ? "Checking…" : "Check again"}
        </button>
      </div>
      {loading && sessions.length === 0 ? (
        <SessionListSkeleton />
      ) : sessions.length === 0 ? (
        <div className="empty-state">
          <h3>No recordings yet</h3>
          <p>
            Start by uploading an MP3, WAV, M4A, or other audio file. When it is
            ready, the coaching notes will appear here.
          </p>
        </div>
      ) : (
        <ul className="session-list">
          {sessions.map((session) => {
            const status = sessionStatus(session.state);
            const selected = selectedId === session.id;
            const action =
              status.tone === "ready"
                ? selected
                  ? "Coaching notes open"
                  : "Read coaching notes"
                : status.tone === "problem"
                  ? "Get help"
                  : "See progress";
            const openHint =
              status.tone === "problem"
                ? "Recovery options are open below. Jumping to help now."
                : status.tone === "ready"
                  ? "Coaching notes are open below."
                  : "Progress is open below.";
            return (
              <li key={session.id}>
                <article
                  className={`session-card${selected ? " session-card--selected" : ""}`}
                >
                  <div className="session-card__topline">
                    <h3>{session.title}</h3>
                    <StatusBadge state={session.state} />
                  </div>
                  <p className="session-card__file">
                    {session.originalFileName}
                  </p>
                  <p className="session-card__meta">
                    Added {formatDate(session.createdAt)}
                  </p>
                  {status.detail && (
                    <p className="session-card__status">{status.detail}</p>
                  )}
                  {session.progress != null &&
                    session.progress < 100 &&
                    !session.error && (
                      <div className="compact-progress">
                        <progress
                          aria-label={`${session.title} progress`}
                          value={session.progress}
                          max="100"
                        />
                        <span>{session.progress}%</span>
                      </div>
                    )}
                  {session.error && (
                    <p className="session-card__error">
                      {session.error.message}
                    </p>
                  )}
                  <button
                    className="button button--secondary"
                    aria-pressed={selectedId === session.id}
                    aria-expanded={selected}
                    aria-controls={detailId}
                    aria-describedby={
                      selected ? `${session.id}-feedback-open-hint` : undefined
                    }
                    onClick={() => onOpen(session.id)}
                  >
                    <span>{action}</span>
                    <span aria-hidden="true">{selected ? "↓" : "›"}</span>
                  </button>
                  {selected && (
                    <p
                      id={`${session.id}-feedback-open-hint`}
                      className="session-card__open-hint"
                    >
                      {openHint}
                    </p>
                  )}
                </article>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function SessionListSkeleton() {
  return (
    <div className="skeleton-list" aria-label="Loading sessions" role="status">
      <span className="sr-only">Loading sessions</span>
      {[1, 2, 3].map((item) => (
        <div className="skeleton-card" key={item} aria-hidden="true" />
      ))}
    </div>
  );
}
