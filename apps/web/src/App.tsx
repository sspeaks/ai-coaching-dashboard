import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  isActiveSessionState,
  type CurrentUser,
  type EvidenceApiClient,
  type SessionDetail,
  type SessionSummary,
} from "@quartet-coach/web-client";
import { formatDate, sessionStatus } from "./lib/format";
import { SessionDetail as SessionDetailView } from "./components/SessionDetail";
import { SessionList } from "./components/SessionList";
import { UploadPanel } from "./components/UploadPanel";

interface AppProps {
  client: EvidenceApiClient;
  mockMode?: boolean;
}

type Route = "feedback" | "upload" | "manage" | "not-found";

export function App({ client, mockMode = false }: AppProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  // One recording is open at a time. The newest opens automatically on the
  // feedback page so singers land on the current summary.
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [route, setRoute] = useState<Route>(() => routeFromPath());
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const [autoOpenSuppressed, setAutoOpenSuppressed] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  const initialRouteRef = useRef(true);
  const openIdRef = useRef(openId);
  openIdRef.current = openId;

  const handleError = useCallback((caught: unknown) => {
    if (caught instanceof DOMException && caught.name === "AbortError") return;
    if (
      caught instanceof ApiError &&
      (caught.status === 401 || caught.status === 403)
    ) {
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
    void client
      .getCurrentUser(controller.signal)
      .then(setCurrentUser)
      .catch(handleError);
    void loadSessions(controller.signal);
    return () => controller.abort();
  }, [client, handleError, loadSessions]);

  useEffect(() => {
    function handlePopState() {
      setRoute(routeFromPath());
    }
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    setError(null);
    if (route !== "feedback") {
      setOpenId(null);
      setAutoOpenSuppressed(false);
    }
    if (initialRouteRef.current) {
      initialRouteRef.current = false;
      return;
    }
    mainRef.current?.focus();
  }, [route]);

  useEffect(() => {
    if (
      route === "feedback" &&
      !openId &&
      !autoOpenSuppressed &&
      sessions.length > 0
    ) {
      setOpenId(sessions[0].id);
    }
  }, [autoOpenSuppressed, openId, route, sessions]);

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
    if (!sessions.some((session) => isActiveSessionState(session.state)))
      return;
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

  function rememberSession(session: SessionDetail) {
    setSessions((current) => {
      const nextSummary = toSummary(session);
      const existing = current.findIndex((item) => item.id === session.id);
      if (existing === -1) return [nextSummary, ...current];
      return current.map((item) =>
        item.id === session.id ? nextSummary : item,
      );
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
    setSessions((current) =>
      current.filter((session) => session.id !== sessionId),
    );
    setDetail(null);
    setOpenId(null);
    setAutoOpenSuppressed(false);
    void loadSessions();
  }

  function navigate(nextRoute: Route) {
    const path = pathForRoute(nextRoute);
    window.history.pushState({}, "", path);
    setRoute(nextRoute);
  }

  if (unauthorized) return <AuthenticationRequired />;

  return (
    <>
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          mainRef.current?.focus();
        }}
      >
        Skip to main content
      </a>
      <header className="app-header">
        <div>
          <p className="brand-kicker">Private quartet archive</p>
          <h1>Quartet coaching</h1>
        </div>
        <div className="account-menu" aria-label="Account">
          {currentUser && (
            <span className="account-menu__user">
              Signed in as {currentUser.username}
            </span>
          )}
          <a
            className="button button--quiet"
            href="/oauth2/sign_out?rd=/signed-out"
          >
            Sign out
          </a>
        </div>
      </header>
      {mockMode && (
        <div className="demo-banner" role="status">
          <strong>Demo mode.</strong> Everything on this page is made-up example
          content.
        </div>
      )}
      <nav className="app-nav" aria-label="Main pages">
        <a
          href="/"
          aria-current={route === "feedback" ? "page" : undefined}
          onClick={(event) => {
            event.preventDefault();
            navigate("feedback");
          }}
        >
          Feedback
        </a>
        <a
          href="/upload"
          aria-current={route === "upload" ? "page" : undefined}
          onClick={(event) => {
            event.preventDefault();
            navigate("upload");
          }}
        >
          Upload
        </a>
        <a
          href="/manage"
          aria-current={route === "manage" ? "page" : undefined}
          onClick={(event) => {
            event.preventDefault();
            navigate("manage");
          }}
        >
          Manage recordings
        </a>
      </nav>
      <main id="main-content" className="app-shell" tabIndex={-1} ref={mainRef}>
        {error && (
          <div className="inline-alert inline-alert--danger" role="alert">
            <span>{error}</span>
            <button
              className="button button--quiet"
              onClick={() => void loadSessions()}
            >
              Try again
            </button>
          </div>
        )}
        {route === "feedback" && (
          <FeedbackPage
            sessions={sessions}
            loadingList={loadingList}
            loadingDetail={loadingDetail}
            detail={detail}
            openId={openId}
            onOpen={(id) => {
              setAutoOpenSuppressed(false);
              setOpenId(id);
            }}
            onClose={() => {
              setAutoOpenSuppressed(true);
              setOpenId(null);
            }}
            onRefresh={() => void loadSessions()}
            onChanged={handleChanged}
            client={client}
            onNavigate={navigate}
          />
        )}
        {route === "upload" && (
          <UploadPage
            client={client}
            onUploaded={handleUploaded}
            onNavigate={navigate}
          />
        )}
        {route === "manage" && (
          <ManagementPage
            sessions={sessions}
            loading={loadingList}
            client={client}
            onRefresh={() => void loadSessions()}
            onChanged={rememberSession}
            onDeleted={handleDeleted}
            onNavigate={navigate}
            onError={handleError}
          />
        )}
        {route === "not-found" && <NotFoundPage onNavigate={navigate} />}
      </main>
    </>
  );
}

function FeedbackPage({
  sessions,
  loadingList,
  loadingDetail,
  detail,
  openId,
  onOpen,
  onClose,
  onRefresh,
  onChanged,
  client,
  onNavigate,
}: {
  sessions: SessionSummary[];
  loadingList: boolean;
  loadingDetail: boolean;
  detail: SessionDetail | null;
  openId: string | null;
  onOpen: (id: string) => void;
  onClose: () => void;
  onRefresh: () => void;
  onChanged: (session: SessionDetail) => void;
  client: EvidenceApiClient;
  onNavigate: (route: Route) => void;
}) {
  const detailRegionId = "feedback-detail-panel";
  const detailRegionRef = useRef<HTMLDivElement>(null);
  const [shouldFocusDetail, setShouldFocusDetail] = useState(false);

  useEffect(() => {
    if (
      !shouldFocusDetail ||
      !openId ||
      loadingDetail ||
      !detail ||
      detail.id !== openId
    ) {
      return;
    }
    const detailRegion = detailRegionRef.current;
    if (!detailRegion) return;
    if (typeof detailRegion.scrollIntoView === "function") {
      detailRegion.scrollIntoView({ block: "start" });
    }
    detailRegion.focus();
    setShouldFocusDetail(false);
  }, [detail, loadingDetail, openId, shouldFocusDetail]);

  function handleOpen(id: string) {
    setShouldFocusDetail(true);
    onOpen(id);
  }

  return (
    <>
      <h2 className="page-section-heading">Coaching feedback</h2>
      <div className="feedback-layout">
        <SessionList
          sessions={sessions}
          loading={loadingList}
          selectedId={openId}
          detailId={detailRegionId}
          onOpen={handleOpen}
          onRefresh={onRefresh}
        />
        <div
          id={detailRegionId}
          ref={detailRegionRef}
          className="feedback-detail"
          role="region"
          aria-label={
            detail && openId === detail.id
              ? `Opened coaching feedback for ${detail.title}`
              : "Coaching feedback detail"
          }
          tabIndex={-1}
        >
          {openId === null ? (
            <section
              className="panel detail-empty"
              aria-labelledby="feedback-empty-heading"
            >
              <h2 id="feedback-empty-heading">
                {sessions.length === 0
                  ? "No feedback yet"
                  : "Select a recording"}
              </h2>
              <p>
                {sessions.length === 0
                  ? "There are no coaching summaries yet. Use Upload in the main navigation when you have a recording to add."
                  : "Choose one recording from the list to read its coaching summary."}
              </p>
            </section>
          ) : loadingDetail || !detail ? (
            <section className="panel detail-loading" role="status">
              <span className="spinner" aria-hidden="true" />
              Opening this recording…
            </section>
          ) : (
            <>
              <button className="back-link" onClick={onClose}>
                ← Choose another recording
              </button>
              <SessionDetailView
                session={detail}
                client={client}
                onChanged={onChanged}
                onDeleted={() => undefined}
                onUploadDifferent={() => onNavigate("upload")}
              />
            </>
          )}
        </div>
      </div>
    </>
  );
}

function NotFoundPage({ onNavigate }: { onNavigate: (route: Route) => void }) {
  return (
    <section
      className="panel not-found-panel"
      aria-labelledby="not-found-heading"
    >
      <p className="eyebrow">Page not found</p>
      <h2 id="not-found-heading">This page does not exist.</h2>
      <p>
        The link may be old, or the address may have been typed wrong. Go back
        to the feedback list to choose a coaching session.
      </p>
      <button
        className="button button--primary"
        onClick={() => onNavigate("feedback")}
      >
        Back to feedback
      </button>
    </section>
  );
}

function UploadPage({
  client,
  onUploaded,
  onNavigate,
}: {
  client: EvidenceApiClient;
  onUploaded: (session: SessionDetail) => void;
  onNavigate: (route: Route) => void;
}) {
  return (
    <>
      <section className="welcome-panel" aria-labelledby="upload-page-heading">
        <p className="eyebrow">Add a recording</p>
        <h2 id="upload-page-heading">Upload one coaching recording.</h2>
        <p>
          Upload lives on its own page so the feedback library stays focused on
          reading and listening.
        </p>
        <div className="page-actions">
          <button
            className="button button--quiet"
            onClick={() => onNavigate("feedback")}
          >
            ← Back to feedback
          </button>
          <button
            className="button button--secondary"
            onClick={() => onNavigate("manage")}
          >
            Manage recordings
          </button>
        </div>
      </section>
      <UploadPanel client={client} onUploaded={onUploaded} />
    </>
  );
}

function ManagementPage({
  sessions,
  loading,
  client,
  onRefresh,
  onChanged,
  onDeleted,
  onNavigate,
  onError,
}: {
  sessions: SessionSummary[];
  loading: boolean;
  client: EvidenceApiClient;
  onRefresh: () => void;
  onChanged: (session: SessionDetail) => void;
  onDeleted: (sessionId: string) => void;
  onNavigate: (route: Route) => void;
  onError: (caught: unknown) => void;
}) {
  const [working, setWorking] = useState<string | null>(null);

  async function run(
    sessionId: string,
    action: string,
    operation: () => Promise<void>,
  ) {
    setWorking(`${action}:${sessionId}`);
    try {
      await operation();
    } catch (caught) {
      onError(caught);
    } finally {
      setWorking(null);
    }
  }

  async function deleteRecording(session: SessionSummary) {
    if (
      !window.confirm(
        `Delete "${session.title}" and its coaching notes? This cannot be undone.`,
      )
    ) {
      return;
    }
    await run(session.id, "delete", async () => {
      await client.deleteSession(session.id);
      onDeleted(session.id);
    });
  }

  return (
    <>
      <section className="welcome-panel" aria-labelledby="management-heading">
        <p className="eyebrow">Recording management</p>
        <h2 id="management-heading">Upload, update, or delete recordings.</h2>
        <p>
          Use this page for recording chores. The feedback page stays focused on
          summaries and source time links.
        </p>
        <div className="page-actions">
          <button
            className="button button--primary"
            onClick={() => onNavigate("upload")}
          >
            Upload a recording
          </button>
          <button
            className="button button--quiet"
            onClick={() => onNavigate("feedback")}
          >
            ← Back to feedback
          </button>
        </div>
      </section>
      <section
        className="panel management-panel"
        aria-labelledby="management-list-heading"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">All recordings</p>
            <h2 id="management-list-heading">Recording controls</h2>
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
            <h3>No recordings to manage</h3>
            <p>
              Upload a recording first, then deletion and update controls appear
              here.
            </p>
            <button
              className="button button--primary"
              onClick={() => onNavigate("upload")}
            >
              Upload a recording
            </button>
          </div>
        ) : (
          <ul className="management-list">
            {sessions.map((session) => (
              <li key={session.id}>
                <article className="management-card">
                  <div>
                    <h3>{session.title}</h3>
                    <p>
                      {session.originalFileName} · Added{" "}
                      {formatDate(session.createdAt)}
                    </p>
                    <p>{sessionStatus(session.state).label}</p>
                  </div>
                  <div className="session-actions">
                    <button
                      className="button button--secondary"
                      disabled={working !== null}
                      onClick={() =>
                        run(session.id, "refresh", async () => {
                          onChanged(await client.refreshFromSpeakr(session.id));
                        })
                      }
                    >
                      {working === `refresh:${session.id}`
                        ? "Checking…"
                        : "Check transcript"}
                    </button>
                    <button
                      className="button button--quiet"
                      disabled={working !== null}
                      onClick={() =>
                        run(session.id, "summary", async () => {
                          await client.regenerateOverview(session.id);
                          onRefresh();
                        })
                      }
                    >
                      {working === `summary:${session.id}`
                        ? "Updating…"
                        : "Update summary"}
                    </button>
                    {isActiveSessionState(session.state) &&
                      session.state !== "DELETE_PENDING" && (
                        <button
                          className="button button--quiet"
                          disabled={working !== null}
                          onClick={() =>
                            run(session.id, "cancel", async () => {
                              onChanged(await client.cancelSession(session.id));
                            })
                          }
                        >
                          {working === `cancel:${session.id}`
                            ? "Cancelling…"
                            : "Cancel"}
                        </button>
                      )}
                    <button
                      className="button button--danger"
                      disabled={working !== null}
                      onClick={() => void deleteRecording(session)}
                    >
                      {working === `delete:${session.id}`
                        ? "Deleting…"
                        : "Delete recording"}
                    </button>
                  </div>
                </article>
              </li>
            ))}
          </ul>
        )}
      </section>
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

function routeFromPath(): Route {
  if (typeof window === "undefined") return "feedback";
  const path = window.location.pathname;
  if (path === "/upload") return "upload";
  if (path === "/manage") return "manage";
  if (path === "/" || path === "/index.html") return "feedback";
  return "not-found";
}

function pathForRoute(route: Route): string {
  if (route === "upload") return "/upload";
  if (route === "manage") return "/manage";
  return "/";
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
