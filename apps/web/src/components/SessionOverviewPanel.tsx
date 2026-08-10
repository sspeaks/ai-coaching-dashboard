import { useEffect, useState } from "react";
import type {
  EvidenceApiClient,
  SessionDetail,
  SessionOverview,
} from "@quartet-coach/web-client";
import { formatTimestampMs } from "../lib/format";

interface SessionOverviewPanelProps {
  session: SessionDetail;
  client: EvidenceApiClient;
  onSeek: (seconds: number) => void;
  audioAvailable: boolean;
  onShowAll: () => void;
  showManagementTools?: boolean;
}

export function SessionOverviewPanel({
  session,
  client,
  onSeek,
  audioAvailable,
  onShowAll,
  showManagementTools = false,
}: SessionOverviewPanelProps) {
  const [overview, setOverview] = useState<SessionOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    client
      .getOverview(session.id, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setOverview(result);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          caught instanceof Error
            ? caught.message
            : "The summary could not be loaded.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [client, session.id, session.updatedAt]);

  async function regenerate() {
    setRegenerating(true);
    setError(null);
    try {
      await client.regenerateOverview(session.id);
      const refreshed = await client.getOverview(session.id);
      setOverview(refreshed);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The summary could not be regenerated.",
      );
    } finally {
      setRegenerating(false);
    }
  }

  if (loading) {
    return (
      <div className="overview-panel" aria-busy="true">
        <p className="supporting-text">Opening the coaching notes…</p>
      </div>
    );
  }

  return (
    <div className="overview-panel">
      <div className="ledger-heading">
        <div>
          <p className="eyebrow">Step 2</p>
          <h3>What the coach worked on</h3>
        </div>
        {showManagementTools && (
          <details className="inline-details">
            <summary>Options</summary>
            <button
              className="button button--quiet button--compact"
              onClick={regenerate}
              disabled={regenerating}
            >
              {regenerating ? "Updating…" : "Update summary"}
            </button>
          </details>
        )}
      </div>

      {error && (
        <div className="inline-alert inline-alert--danger" role="alert">
          {error}
        </div>
      )}

      {overview?.stale && (
        <div className="inline-alert" role="status">
          <strong>This summary may be out of date.</strong> Someone changed the
          detailed notes after it was written. Use the management page to update it.
        </div>
      )}

      {!overview || overview.themes.length === 0 ? (
        <div className="empty-state">
          <h3>No summary yet</h3>
          <p>
            {session.interventionCount > 0
              ? "The detailed notes are available. Use the management page to create a short summary."
              : "The coaching notes will appear after the recording is ready."}
          </p>
        </div>
      ) : (
        <>
          <ol className="theme-list">
            {overview.themes.map((theme) => (
              <li key={theme.rank} className="theme-item">
                <div className="theme-item__header">
                  <h4>
                    <span className="theme-item__rank">{theme.rank}</span>
                    {theme.title}
                  </h4>
                </div>
                <p>{theme.summary}</p>
                <div className="theme-item__moments">
                  <span className="supporting-text">
                    {theme.moments.length === 1
                      ? "Hear it at"
                      : `Hear the ${theme.moments.length} source moments`}
                  </span>
                  {theme.moments.map((moment) => (
                    <button
                      key={moment.interventionId}
                      className="evidence-link"
                      onClick={() => onSeek(moment.startMs / 1000)}
                      disabled={!audioAvailable}
                      title={
                        audioAvailable
                          ? "Play the recording from this moment"
                          : "Audio playback is not available for this session"
                      }
                    >
                      {formatTimestampMs(moment.startMs)}
                    </button>
                  ))}
                </div>
              </li>
            ))}
          </ol>
          <p className="supporting-text">
            This summary is made only from timestamped coaching notes. Use the
            time buttons to hear the source; exact quotes are shown only when
            the transcript captured the coach's words verbatim.
          </p>
        </>
      )}

      <button className="button button--secondary" onClick={onShowAll}>
        See every coaching note ({session.interventionCount})
      </button>
    </div>
  );
}
