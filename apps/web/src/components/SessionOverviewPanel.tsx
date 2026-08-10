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
}

export function SessionOverviewPanel({
  session,
  client,
  onSeek,
  audioAvailable,
  onShowAll,
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
        <p className="supporting-text">Loading the session summary…</p>
      </div>
    );
  }

  return (
    <div className="overview-panel">
      <div className="ledger-heading">
        <div>
          <p className="eyebrow">What the coach worked on</p>
          <h3>Session summary</h3>
        </div>
        <button
          className="button button--quiet"
          onClick={regenerate}
          disabled={regenerating}
        >
          {regenerating ? "Regenerating…" : "Regenerate summary"}
        </button>
      </div>

      {error && (
        <div className="inline-alert inline-alert--danger" role="alert">
          {error}
        </div>
      )}

      {overview?.stale && (
        <div className="inline-alert" role="status">
          <strong>This summary is out of date.</strong> The ledger changed after
          it was written, so it does not reflect your latest review.
        </div>
      )}

      {!overview || overview.themes.length === 0 ? (
        <p className="missing-value">
          {session.interventionCount > 0
            ? "This session has not been summarized yet."
            : "There is nothing to summarize until the recording has been processed."}
        </p>
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
                  <button
                    className="evidence-link"
                    onClick={() => onSeek(theme.startMs / 1000)}
                    disabled={!audioAvailable}
                    title={
                      audioAvailable
                        ? "Play the recording from here"
                        : "Audio playback is not available for this session"
                    }
                  >
                    <strong>{formatTimestampMs(theme.startMs)}</strong>
                    <span>–{formatTimestampMs(theme.endMs)}</span>
                  </button>
                </div>
                <p>{theme.summary}</p>
                <p className="supporting-text">
                  Based on {theme.interventionIds.length}{" "}
                  {theme.interventionIds.length === 1
                    ? "intervention"
                    : "interventions"}
                </p>
              </li>
            ))}
          </ol>
          <p className="supporting-text">
            Summarized from {overview.interventionCount} recorded interventions.
            Each item points at where its evidence sits in the recording.
          </p>
        </>
      )}

      <button className="button button--secondary" onClick={onShowAll}>
        Show all {session.interventionCount} interventions
      </button>
    </div>
  );
}
