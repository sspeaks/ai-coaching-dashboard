import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  isActiveSessionState,
  type EvidenceApiClient,
  type SessionDetail,
  type SessionSummary,
} from "@quartet-coach/web-client";
import { SessionDetail as SessionDetailView } from "./components/SessionDetail";
import { SessionList } from "./components/SessionList";
import { UploadPanel } from "./components/UploadPanel";

interface AppProps {
  client: EvidenceApiClient;
  mockMode?: boolean;
}

export function App({ client, mockMode = false }: AppProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;

  const handleError = useCallback((caught: unknown) => {
    if (caught instanceof DOMException && caught.name === "AbortError") return;
    if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
      setUnauthorized(true);
      return;
    }
    setError(caught instanceof Error ? caught.message : "The request failed.");
  }, []);

  const loadSessions = useCallback(
    async (signal?: AbortSignal) => {
      setLoadingList(true);
      setError(null);
      try {
        const next = await client.listSessions(signal);
        setSessions(next);
        const current = selectedIdRef.current;
        if (!current || !next.some((session) => session.id === current)) {
          setSelectedId(next[0]?.id ?? null);
        }
      } catch (caught) {
        handleError(caught);
      } finally {
        setLoadingList(false);
      }
    },
    [client, handleError],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadSessions(controller.signal);
    return () => controller.abort();
  }, [loadSessions]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setLoadingDetail(true);
    setError(null);
    client
      .getSession(selectedId, controller.signal)
      .then(setDetail)
      .catch(handleError)
      .finally(() => setLoadingDetail(false));
    return () => controller.abort();
  }, [client, handleError, selectedId]);

  useEffect(() => {
    if (!sessions.some((session) => isActiveSessionState(session.state))) return;
    const timer = window.setInterval(() => void loadSessions(), 10_000);
    return () => window.clearInterval(timer);
  }, [loadSessions, sessions]);

  useEffect(() => {
    if (!detail || !isActiveSessionState(detail.state)) return;
    const sessionId = detail.id;
    const timer = window.setInterval(() => {
      client
        .getSession(sessionId)
        .then((next) => {
          setDetail(next);
          setSessions((current) =>
            current.map((item) =>
              item.id === next.id ? toSummary(next) : item,
            ),
          );
        })
        .catch(handleError);
    }, 8_000);
    return () => window.clearInterval(timer);
  }, [client, detail?.id, detail?.state, handleError]);

  function upsertSession(session: SessionDetail) {
    setDetail(session);
    setSelectedId(session.id);
    setSessions((current) => {
      const nextSummary = toSummary(session);
      const existing = current.findIndex((item) => item.id === session.id);
      if (existing === -1) return [nextSummary, ...current];
      return current.map((item) => (item.id === session.id ? nextSummary : item));
    });
  }

  function handleDeleted(sessionId: string) {
    setSessions((current) => current.filter((session) => session.id !== sessionId));
    setDetail(null);
    setSelectedId(null);
    void loadSessions();
  }

  if (unauthorized) return <AuthenticationRequired />;

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="app-header">
        <div>
          <p className="brand-kicker">Private coaching archive</p>
          <h1>Evidence Ledger</h1>
        </div>
        <div className="header-actions">
          <span className="protected-label">Authenticated access</span>
          <a className="button button--quiet" href="/oauth2/sign_out">
            Sign out
          </a>
        </div>
      </header>
      {mockMode && (
        <div className="demo-banner" role="status">
          <strong>Local demo data mode.</strong> No requests are being sent to the
          evidence API, and all displayed content is synthetic.
        </div>
      )}
      <main id="main-content" className="app-shell">
        <UploadPanel client={client} onUploaded={upsertSession} />
        {error && (
          <div className="inline-alert inline-alert--danger app-error" role="alert">
            <span>{error}</span>
            <button className="button button--quiet" onClick={() => void loadSessions()}>
              Try again
            </button>
          </div>
        )}
        <div className="workspace">
          <SessionList
            sessions={sessions}
            selectedId={selectedId}
            loading={loadingList}
            onSelect={setSelectedId}
            onRefresh={() => void loadSessions()}
          />
          {loadingDetail ? (
            <section className="panel detail-loading" role="status">
              <span className="spinner" aria-hidden="true" />
              Loading session evidence…
            </section>
          ) : detail ? (
            <SessionDetailView
              session={detail}
              client={client}
              onChanged={upsertSession}
              onDeleted={handleDeleted}
            />
          ) : (
            <section className="panel detail-empty">
              <h2>Select a session</h2>
              <p>
                Choose a session to review processing status, source audio, and
                evidence-linked coaching interventions.
              </p>
            </section>
          )}
        </div>
      </main>
    </>
  );
}

function AuthenticationRequired() {
  const returnTo =
    typeof window === "undefined"
      ? "/"
      : `${window.location.pathname}${window.location.search}`;
  return (
    <main className="auth-screen">
      <section className="panel auth-card">
        <p className="eyebrow">Protected archive</p>
        <h1>Sign in required</h1>
        <p>
          Your authenticated session is missing or no longer valid. The browser
          never receives Speakr credentials.
        </p>
        <a
          className="button button--primary"
          href={`/oauth2/sign_in?rd=${encodeURIComponent(returnTo)}`}
        >
          Sign in
        </a>
      </section>
    </main>
  );
}

function toSummary(session: SessionDetail): SessionSummary {
  const {
    interventions: _interventions,
    audioUrl: _audioUrl,
    audioMimeType: _audioMimeType,
    speakrSessionUrl: _speakrSessionUrl,
    ...summary
  } = session;
  return summary;
}
