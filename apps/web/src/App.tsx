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
  // One recording is open at a time. Nothing opens on its own, so the app
  // always starts on the short list a singer recognises.
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const openIdRef = useRef(openId);
  openIdRef.current = openId;

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
        const current = openIdRef.current;
        if (current && !next.some((session) => session.id === current)) {
          setOpenId(null);
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
    if (!openId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setLoadingDetail(true);
    setError(null);
    client
      .getSession(openId, controller.signal)
      .then(setDetail)
      .catch(handleError)
      .finally(() => setLoadingDetail(false));
    return () => controller.abort();
  }, [client, handleError, openId]);

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
            current.map((item) => (item.id === next.id ? toSummary(next) : item)),
          );
        })
        .catch(handleError);
    }, 8_000);
    return () => window.clearInterval(timer);
  }, [client, detail?.id, detail?.state, handleError]);

  function rememberSession(session: SessionDetail) {
    setSessions((current) => {
      const nextSummary = toSummary(session);
      const existing = current.findIndex((item) => item.id === session.id);
      if (existing === -1) return [nextSummary, ...current];
      return current.map((item) => (item.id === session.id ? nextSummary : item));
    });
  }

  function handleChanged(session: SessionDetail) {
    setDetail(session);
    rememberSession(session);
  }

  // An upload is added to the list but does not steal the screen: there is
  // nothing to read until processing finishes.
  function handleUploaded(session: SessionDetail) {
    rememberSession(session);
  }

  function handleDeleted(sessionId: string) {
    setSessions((current) => current.filter((session) => session.id !== sessionId));
    setDetail(null);
    setOpenId(null);
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
          <p className="brand-kicker">Private quartet archive</p>
          <h1>Quartet coaching</h1>
        </div>
        <a className="button button--quiet" href="/oauth2/sign_out">
          Sign out
        </a>
      </header>
      {mockMode && (
        <div className="demo-banner" role="status">
          <strong>Demo mode.</strong> Everything on this page is made-up example
          content.
        </div>
      )}
      <main id="main-content" className="app-shell">
        {error && (
          <div className="inline-alert inline-alert--danger" role="alert">
            <span>{error}</span>
            <button className="button button--quiet" onClick={() => void loadSessions()}>
              Try again
            </button>
          </div>
        )}
        {openId === null ? (
          <>
            <section className="welcome-panel" aria-labelledby="welcome-heading">
              <p className="eyebrow">For quartet members</p>
              <h2 id="welcome-heading">Upload a recording. Read the coaching notes.</h2>
              <p>
                Choose an audio file from rehearsal or coaching. We listen for the
                coach's feedback, summarize the main points, and keep every point
                linked to the place in the recording it came from.
              </p>
            </section>
            <UploadPanel client={client} onUploaded={handleUploaded} />
            <SessionList
              sessions={sessions}
              loading={loadingList}
              onOpen={setOpenId}
              onRefresh={() => void loadSessions()}
            />
          </>
        ) : (
          <>
            <button className="back-link" onClick={() => setOpenId(null)}>
              ← All recordings
            </button>
            {loadingDetail || !detail ? (
              <section className="panel detail-loading" role="status">
                <span className="spinner" aria-hidden="true" />
                Opening this recording…
              </section>
            ) : (
              <SessionDetailView
                session={detail}
                client={client}
                onChanged={handleChanged}
                onDeleted={handleDeleted}
              />
            )}
          </>
        )}
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
        <h1>Please sign in</h1>
        <p>Your sign-in has expired. Sign in again to see your recordings.</p>
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
