import type { SessionSummary } from "@quartet-coach/web-client";
import { formatDate } from "../lib/format";
import { StatusBadge } from "./StatusBadge";

interface SessionListProps {
  sessions: SessionSummary[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}

export function SessionList({
  sessions,
  selectedId,
  loading,
  onSelect,
  onRefresh,
}: SessionListProps) {
  return (
    <section className="panel session-list-panel" aria-labelledby="sessions-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Archive</p>
          <h2 id="sessions-heading">Coaching sessions</h2>
        </div>
        <button
          className="button button--quiet button--compact"
          onClick={onRefresh}
          disabled={loading}
        >
          {loading ? "Refreshing…" : "Refresh list"}
        </button>
      </div>
      {loading && sessions.length === 0 ? (
        <SessionListSkeleton />
      ) : sessions.length === 0 ? (
        <div className="empty-state">
          <h3>No recordings yet</h3>
          <p>Upload a recording to start its processing and review record.</p>
        </div>
      ) : (
        <ul className="session-list">
          {sessions.map((session) => (
            <li key={session.id}>
              <button
                className={`session-card ${
                  session.id === selectedId ? "session-card--selected" : ""
                }`}
                onClick={() => onSelect(session.id)}
                aria-pressed={session.id === selectedId}
              >
                <span className="session-card__topline">
                  <strong>{session.title}</strong>
                  <StatusBadge state={session.state} />
                </span>
                <span className="session-card__file">{session.originalFileName}</span>
                <span className="session-card__meta">
                  <span>{formatDate(session.createdAt)}</span>
                  <span>
                    {session.reviewedInterventionCount}/
                    {session.interventionCount} reviewed
                  </span>
                </span>
                {session.progress != null &&
                  session.progress < 100 &&
                  !session.error && (
                    <progress
                      aria-label={`${session.title} processing progress`}
                      value={session.progress}
                      max="100"
                    />
                  )}
                {session.error && (
                  <span className="session-card__error">{session.error.message}</span>
                )}
              </button>
            </li>
          ))}
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
