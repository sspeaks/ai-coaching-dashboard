import type { SessionSummary } from "@quartet-coach/web-client";
import { formatDate, sessionStatus } from "../lib/format";
import { StatusBadge } from "./StatusBadge";

interface SessionListProps {
  sessions: SessionSummary[];
  loading: boolean;
  onOpen: (id: string) => void;
  onRefresh: () => void;
}

export function SessionList({
  sessions,
  loading,
  onOpen,
  onRefresh,
}: SessionListProps) {
  return (
    <section className="panel session-list-panel" aria-labelledby="sessions-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Your recordings</p>
          <h2 id="sessions-heading">Feedback library</h2>
        </div>
        <button
          className="button button--quiet button--compact"
          onClick={onRefresh}
          disabled={loading}
        >
          {loading ? "Checking…" : "Check for updates"}
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
            const action = status.tone === "ready" ? "Read feedback" : "See progress";
            return (
              <li key={session.id}>
                <article className="session-card">
                  <div className="session-card__topline">
                    <h3>{session.title}</h3>
                    <StatusBadge state={session.state} />
                  </div>
                  <p className="session-card__file">{session.originalFileName}</p>
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
                    <p className="session-card__error">{session.error.message}</p>
                  )}
                  <button
                    className="button button--secondary"
                    onClick={() => onOpen(session.id)}
                  >
                    {action}
                  </button>
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
