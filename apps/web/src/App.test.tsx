import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  EvidenceApiClient,
  SessionDetail,
} from "@quartet-coach/web-client";
import { App } from "./App";

function createSession(): SessionDetail {
  return {
    id: "session-1",
    title: "Review session",
    originalFileName: "recording.wav",
    createdAt: "2026-08-06T18:00:00.000Z",
    updatedAt: "2026-08-06T18:00:00.000Z",
    state: "AWAITING_REVIEW",
    progress: 100,
    durationMs: 300_000,
    interventionCount: 1,
    reviewedInterventionCount: 0,
    audioUrl: "data:audio/wav;base64,UklGRg==",
    audioMimeType: "audio/wav",
    speakrSessionUrl: null,
    interventions: [
      {
        id: "intervention-1",
        topic: "Breath plan",
        exactCoachFeedback: "Use only source-supported feedback.",
        interpretation: null,
        appliesTo: null,
        songReference: null,
        problemBefore: null,
        exerciseOrRequestedChange: null,
        observedResult: null,
        nextAction: null,
        unresolvedQuestion: "Speaker identity is uncertain.",
        confidence: 0.61,
        uncertaintyReasons: ["Speaker identity needs human confirmation."],
        verificationStatus: "UNVERIFIED",
        evidence: [
          {
            id: "evidence-1",
            role: "COACH_FEEDBACK",
            label: "Feedback",
            startMs: 42_000,
            endMs: 48_000,
          },
        ],
      },
    ],
  };
}

function createClient(session = createSession()): EvidenceApiClient {
  return {
    getCurrentUser: vi.fn(async () => ({
      username: "reverie",
    })),
    listSessions: vi.fn(async () => [
      {
        ...session,
        interventions: undefined,
      } as never,
    ]),
    getSession: vi.fn(async () => session),
    initiateUpload: vi.fn(),
    uploadFile: vi.fn(),
    completeUpload: vi.fn(),
    refreshFromSpeakr: vi.fn(async () => session),
    reviewIntervention: vi.fn(
      async (_sessionId, _interventionId, review): Promise<SessionDetail> => ({
        ...session,
        state: "COMPLETE",
        reviewedInterventionCount: 1,
        interventions: [
          {
            ...session.interventions[0],
            verificationStatus: review.verificationStatus,
          },
        ],
      }),
    ),
    cancelSession: vi.fn(async () => ({ ...session, state: "CANCELLED" })),
    deleteSession: vi.fn(async () => undefined),
    getOverview: vi.fn(async () => ({
      id: "overview-1",
      themes: [
        {
          rank: 1,
          title: "Releasing the sound",
          summary: "The coach worked on releasing jaw tension on the F.",
          interventionIds: ["intervention-1"],
          moments: [
            {
              interventionId: "intervention-1",
              startMs: 42_000,
              endMs: 48_000,
            },
          ],
          startMs: 42_000,
          endMs: 48_000,
        },
      ],
      interventionCount: 1,
      stale: false,
      generatedAt: new Date().toISOString(),
    })),
    regenerateOverview: vi.fn(async () => undefined),
  };
}

function findShowAllInterventions() {
  return screen.findByRole("button", { name: /see every coaching note/i });
}

async function openFirstRecording(user = userEvent.setup()) {
  await user.click(
    await screen.findByRole("button", { name: /read feedback|feedback open/i }),
  );
  return user;
}

function setMediaDuration(audio: HTMLAudioElement, duration: number) {
  Object.defineProperty(audio, "duration", {
    configurable: true,
    value: duration,
  });
}

function deferredPromise<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

function expectToPrecede(first: Element, second: Element) {
  expect(
    first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
}

async function playFirstLedgerMoment(
  user: ReturnType<typeof userEvent.setup>,
  container: HTMLElement,
) {
  await openFirstRecording(user);
  await user.click(await findShowAllInterventions());
  const evidence = await screen.findByRole("button", {
    name: /play coach feedback at 0:42.*feedback/i,
  });
  const audio = container.querySelector("audio");
  expect(audio).not.toBeNull();
  await user.click(evidence);
  return { audio: audio!, evidence };
}

describe("evidence ledger app", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/");
  });

  it("makes the skip link the first tab stop and moves focus to main content", async () => {
    const user = userEvent.setup();
    render(<App client={createClient()} />);

    const skipLink = screen.getByRole("link", { name: "Skip to main content" });
    await user.tab();
    expect(skipLink).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("shows the signed-in username and sends logout through the sticky sign-out route", async () => {
    const client = createClient();
    render(<App client={client} />);

    expect(await screen.findByText("Signed in as reverie")).toBeVisible();
    expect(screen.getByRole("link", { name: "Sign out" })).toHaveAttribute(
      "href",
      "/oauth2/sign_out?rd=/signed-out",
    );
  });

  it.each([
    ["/", "Coaching feedback"],
    ["/upload", "Upload one coaching recording."],
    ["/manage", "Recording controls"],
    ["/not-a-real-page", "This page does not exist."],
  ])("shows account controls on %s", async (path, pageText) => {
    window.history.pushState({}, "", path);
    render(<App client={createClient()} />);

    expect(await screen.findByText(pageText)).toBeVisible();
    expect(screen.getByText("Signed in as reverie")).toBeVisible();
    expect(screen.getByRole("link", { name: "Sign out" })).toHaveAttribute(
      "href",
      "/oauth2/sign_out?rd=/signed-out",
    );
  });

  it("uploads a recording through the client abstraction", async () => {
    const user = userEvent.setup();
    const uploaded = {
      ...createSession(),
      id: "uploaded-session",
      title: "Practice upload",
      originalFileName: "practice.wav",
      state: "UPLOADED" as const,
      interventions: [],
      interventionCount: 0,
    };
    const client = createClient();
    vi.mocked(client.listSessions).mockResolvedValue([]);
    vi.mocked(client.initiateUpload).mockResolvedValue({
      session: uploaded,
      upload: { id: "upload-1", url: "/storage/upload", method: "PUT" },
    });
    vi.mocked(client.uploadFile).mockImplementation(
      async (_target, _file, onProgress) => onProgress(100),
    );
    vi.mocked(client.completeUpload).mockResolvedValue(uploaded);
    render(<App client={client} />);

    await screen.findByText("No recordings yet");
    expect(screen.queryByLabelText(/recording name/i)).toBeNull();
    expect(
      screen.getByRole("button", { name: "Upload a recording" }),
    ).toBeVisible();
    await user.click(screen.getByRole("link", { name: "Upload" }));
    expect(
      screen.getByText("Example: August coaching with Alex"),
    ).toBeVisible();
    expect(
      screen.getByPlaceholderText("August coaching"),
    ).toHaveAccessibleDescription("Example: August coaching with Alex");
    expect(
      screen.getByText("Drag an audio file here or choose a file"),
    ).toBeVisible();
    expect(screen.getByText("Audio is stored here.")).toBeVisible();
    expect(screen.getByText("Audio is sent for transcription.")).toBeVisible();
    expect(screen.getByText("Text may be analyzed by AI.")).toBeVisible();
    expect(screen.getByText("Deletion is explicit.")).toBeVisible();
    expect(
      screen.getByText(/make sure everyone on the recording is okay/i),
    ).toBeVisible();
    const disclosure = screen.getByRole("button", {
      name: /what happens to my recording/i,
    });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.getByText(/original file is kept until an admin deletes/i),
    ).not.toBeVisible();
    await user.click(disclosure);
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText(/original file is kept until an admin deletes/i),
    ).toBeVisible();
    expect(screen.getByText(/uses OpenAI for transcription/i)).toBeVisible();
    expect(screen.getByText(/transcript text and note text/i)).toBeVisible();
    expect(screen.getByText(/deletion does not finish/i)).toBeVisible();
    await user.type(
      screen.getByLabelText(/recording name/i),
      "Practice upload",
    );
    await user.upload(
      screen.getByLabelText("Audio file"),
      new File(["recording"], "practice.wav", { type: "audio/wav" }),
    );
    expect(screen.getByText("practice.wav selected")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Upload recording" }));

    await waitFor(() =>
      expect(client.completeUpload).toHaveBeenCalledWith(
        "uploaded-session",
        "upload-1",
      ),
    );
    expect(
      await screen.findByText(/Practice upload was uploaded/i),
    ).toBeVisible();
  });

  it("keeps recording management off the feedback page", async () => {
    const user = userEvent.setup();
    const client = createClient();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<App client={client} />);

    await screen.findByText("Choose a coaching session");
    expect(
      screen.queryByRole("button", { name: /delete recording/i }),
    ).toBeNull();
    await user.click(screen.getByRole("link", { name: "Manage recordings" }));
    expect(await screen.findByText("Recording controls")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /delete recording/i }));

    await waitFor(() =>
      expect(client.deleteSession).toHaveBeenCalledWith("session-1"),
    );
  });

  it("opens the newest session summary with playable source moments beside the advice", async () => {
    const client = createClient();
    render(<App client={client} />);

    // The dense ledger is a drill-down; the headline items are what a singer
    // should land on after a rehearsal.
    expect(await screen.findByText("Releasing the sound")).toBeVisible();
    expect(screen.getByText(/releasing jaw tension on the F/i)).toBeVisible();
    expect(screen.getByText("Play the source moment")).toBeVisible();
    expect(
      screen.getByRole("button", { name: /play source at 0:42/i }),
    ).toBeVisible();
    expect(screen.queryByText("1 source moment")).toBeNull();
    expect(
      screen.queryByText("Speaker identity needs human confirmation."),
    ).toBeNull();
  });

  it("keeps summary source moments visible but disabled when audio is unavailable", async () => {
    const client = createClient({ ...createSession(), audioUrl: null });
    render(<App client={client} />);

    expect(await screen.findByText("Releasing the sound")).toBeVisible();
    const sourceMoment = screen.getByRole("button", {
      name: /play source at 0:42/i,
    });
    expect(sourceMoment).toBeVisible();
    expect(sourceMoment).toBeDisabled();
    expect(sourceMoment).toHaveAttribute(
      "title",
      "Audio playback is not available for this session",
    );
  });

  it("exposes feedback disclosure state and moves focus to newly opened notes", async () => {
    const user = userEvent.setup();
    const first = createSession();
    const second = {
      ...createSession(),
      id: "session-2",
      title: "Second rehearsal",
      originalFileName: "second.wav",
    };
    const client = createClient(first);
    vi.mocked(client.listSessions).mockResolvedValue([
      { ...first, interventions: undefined } as never,
      { ...second, interventions: undefined } as never,
    ]);
    vi.mocked(client.getSession).mockImplementation(async (id) =>
      id === "session-2" ? second : first,
    );
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    render(<App client={client} />);

    expect(
      await screen.findByRole("button", { name: /feedback open/i }),
    ).toBeVisible();
    expect(
      await screen.findByRole("heading", { name: "Review session", level: 2 }),
    ).toBeVisible();
    const secondCard = screen.getByText("Second rehearsal").closest("article");
    expect(secondCard).not.toBeNull();
    const secondButton = within(secondCard!).getByRole("button", {
      name: /read feedback/i,
    });
    expect(secondButton).toHaveAttribute("aria-expanded", "false");
    expect(secondButton).toHaveAttribute(
      "aria-controls",
      "feedback-detail-panel",
    );
    await user.click(secondButton);

    const openButton = await screen.findByRole("button", {
      name: /feedback open/i,
    });
    expect(openButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/feedback is open below/i)).toBeVisible();
    expect(
      await screen.findByRole("heading", {
        name: "Second rehearsal",
        level: 2,
      }),
    ).toBeVisible();
    const detailRegion = screen.getByLabelText(
      "Opened coaching feedback for Second rehearsal",
    );
    await waitFor(() => expect(detailRegion).toHaveFocus());
    expect(scrollIntoView).toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", { name: /choose another recording/i }),
    );
    expect(screen.getByText("Select a recording")).toBeVisible();
    expect(document.getElementById("feedback-detail-panel")).not.toBeNull();
    expect(secondButton).toHaveAttribute(
      "aria-controls",
      "feedback-detail-panel",
    );
  });

  it("does not auto-open anything when there are no sessions", async () => {
    const client = createClient();
    vi.mocked(client.listSessions).mockResolvedValue([]);
    render(<App client={client} />);

    expect(
      await screen.findByRole("heading", {
        name: "Upload your first rehearsal recording",
      }),
    ).toBeVisible();
    expect(screen.getByText("What happens next")).toBeVisible();
    expect(client.getSession).not.toHaveBeenCalled();
  });

  it("uses the empty first-run space to guide upload and explain the next steps", async () => {
    const user = userEvent.setup();
    const client = createClient();
    vi.mocked(client.listSessions).mockResolvedValue([]);
    render(<App client={client} />);

    expect(await screen.findByText("No recordings yet")).toBeVisible();
    expect(
      screen.getByRole("heading", {
        name: "Upload your first rehearsal recording",
      }),
    ).toBeVisible();
    expect(screen.getByText("1. Choose your audio file")).toBeVisible();
    expect(screen.getByText("2. We listen to the recording")).toBeVisible();
    expect(screen.getByText("3. Coaching notes appear here")).toBeVisible();
    expect(screen.getByRole("link", { name: "Upload" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Upload a recording" }));

    expect(await screen.findByText("Upload one coaching recording.")).toBeVisible();
    expect(screen.getByLabelText(/recording name/i)).toBeVisible();
  });

  it("shows drag affordance, selected-file feedback, and live upload progress", async () => {
    const user = userEvent.setup();
    const uploadFinished = deferredPromise<void>();
    const uploaded = {
      ...createSession(),
      id: "drag-upload-session",
      title: "Dragged upload",
      originalFileName: "quartet.wav",
      state: "UPLOADED" as const,
      interventions: [],
      interventionCount: 0,
    };
    const client = createClient();
    vi.mocked(client.listSessions).mockResolvedValue([]);
    vi.mocked(client.initiateUpload).mockResolvedValue({
      session: uploaded,
      upload: { id: "upload-2", url: "/storage/upload", method: "PUT" },
    });
    vi.mocked(client.uploadFile).mockImplementation(
      async (_target, _file, onProgress) => {
        onProgress(46);
        await uploadFinished.promise;
      },
    );
    vi.mocked(client.completeUpload).mockResolvedValue(uploaded);
    render(<App client={client} />);

    await user.click(await screen.findByRole("button", { name: "Upload a recording" }));
    const dropzone = screen
      .getByText("Drag an audio file here or choose a file")
      .closest("label");
    expect(dropzone).not.toBeNull();

    fireEvent.dragEnter(dropzone!, {
      dataTransfer: { files: [] },
    });
    expect(screen.getByText("Drop the recording here")).toBeVisible();

    const file = new File(["recording"], "quartet.wav", { type: "audio/wav" });
    fireEvent.drop(dropzone!, {
      dataTransfer: { files: [file] },
    });

    expect(screen.getByText("quartet.wav selected")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Upload recording" }));
    expect(await screen.findByText("Uploading quartet.wav")).toBeVisible();
    expect(screen.getAllByText("46%").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Uploading…" })).toBeDisabled();

    uploadFinished.resolve();

    await waitFor(() =>
      expect(client.completeUpload).toHaveBeenCalledWith(
        "drag-upload-session",
        "upload-2",
      ),
    );
  });

  it("auto-opens the newest processing session", async () => {
    const processing = {
      ...createSession(),
      id: "processing-session",
      title: "Newest processing take",
      state: "TRANSCRIBING" as const,
      progress: 42,
      audioUrl: null,
      interventions: [],
      interventionCount: 0,
    };
    const older = {
      ...createSession(),
      id: "older-session",
      title: "Older take",
    };
    const client = createClient(processing);
    vi.mocked(client.listSessions).mockResolvedValue([
      { ...processing, interventions: undefined } as never,
      { ...older, interventions: undefined } as never,
    ]);
    vi.mocked(client.getSession).mockImplementation(async (id) => {
      if (id === "processing-session") return processing;
      return older;
    });

    render(<App client={client} />);

    expect(await screen.findByText("Newest processing take")).toBeVisible();
    expect(await screen.findByText("42%")).toBeVisible();
    expect(
      await screen.findByText("Coaching notes are not ready yet"),
    ).toBeVisible();
    expect(client.getSession).toHaveBeenCalledWith(
      "processing-session",
      expect.any(AbortSignal),
    );
  });

  it("auto-opens the newest failed session with recovery actions", async () => {
    const user = userEvent.setup();
    const failed = {
      ...createSession(),
      id: "failed-session",
      title: "Newest failed take",
      state: "FAILED" as const,
      error: { message: "Speakr could not read the file.", retryable: true },
      interventions: [],
      interventionCount: 0,
    };
    const older = {
      ...createSession(),
      id: "older-session",
      title: "Older take",
    };
    const client = createClient(failed);
    vi.mocked(client.listSessions).mockResolvedValue([
      { ...failed, interventions: undefined } as never,
      { ...older, interventions: undefined } as never,
    ]);
    vi.mocked(client.getSession).mockImplementation(async (id) => {
      if (id === "failed-session") return failed;
      return older;
    });

    render(<App client={client} />);

    expect(await screen.findByText("Newest failed take")).toBeVisible();
    expect(screen.getByRole("button", { name: "Recover" })).toBeVisible();
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "This file could not be read.",
      ),
    );
    expect(
      screen.getByText(/Upload a different MP3, WAV, or M4A file/i),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() =>
      expect(client.refreshFromSpeakr).toHaveBeenCalledWith("failed-session"),
    );
    await user.click(
      screen.getByRole("button", { name: "Upload a different file" }),
    );
    expect(
      await screen.findByText("Upload one coaching recording."),
    ).toBeVisible();
    expect(client.getSession).toHaveBeenCalledWith(
      "failed-session",
      expect.any(AbortSignal),
    );
  });

  it("treats /index.html as a feedback alias for post-login defense-in-depth (issue #28)", async () => {
    const client = createClient();
    // oauth2-proxy may redirect to /index.html if Caddy try_files fires before
    // forward_auth captures the original path. The SPA must handle this
    // gracefully as a known alias.
    window.history.pushState({}, "", "/index.html");
    render(<App client={client} />);

    expect(await screen.findByText("Coaching feedback")).toBeVisible();
    // Auto-open fires for the newest session
    expect(await screen.findByText("Review session")).toBeVisible();
    expect(screen.queryByText("This page does not exist.")).toBeNull();
  });

  it("shows a plain-language page for genuinely unknown URLs (issue #17)", async () => {
    const user = userEvent.setup();
    const client = createClient();
    window.history.pushState({}, "", "/not-a-real-page");
    render(<App client={client} />);

    expect(await screen.findByText("This page does not exist.")).toBeVisible();
    expect(screen.getByText(/go back to the feedback list/i)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Back to feedback" }));
    expect(await screen.findByText("Coaching feedback")).toBeVisible();
    await waitFor(() => expect(screen.getByRole("main")).toHaveFocus());
  });

  it("warns when the summary no longer matches the reviewed ledger", async () => {
    const user = userEvent.setup();
    const client = createClient();
    client.getOverview = vi.fn(async () => ({
      id: "overview-1",
      themes: [],
      interventionCount: 1,
      stale: true,
      generatedAt: new Date().toISOString(),
    }));
    render(<App client={client} />);

    await openFirstRecording(user);
    expect(
      await screen.findByText(/summary may be out of date/i),
    ).toBeVisible();
  });

  it("shows uncertainty and saves a human verification decision", async () => {
    const user = userEvent.setup();
    const client = createClient();
    render(<App client={client} />);

    await openFirstRecording(user);
    await user.click(await findShowAllInterventions());
    expect(
      await screen.findByText("Speaker identity needs human confirmation."),
    ).not.toBeVisible();
    await user.click(screen.getByText(/why might this be wrong/i));
    expect(
      screen.getByText("Speaker identity needs human confirmation."),
    ).toBeVisible();
    expect(screen.getByText(/does not prove the coach's point/i)).toBeVisible();

    await user.click(screen.getByLabelText("Looks right"));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(client.reviewIntervention).toHaveBeenCalledWith(
        "session-1",
        "intervention-1",
        { verificationStatus: "VERIFIED", note: null },
      ),
    );
    expect(await screen.findByText("Checked")).toBeVisible();
  });

  it("puts the coaching takeaway before review warnings while keeping warnings reachable", async () => {
    const user = userEvent.setup();
    render(<App client={createClient()} />);

    await openFirstRecording(user);
    await user.click(await findShowAllInterventions());
    const note = (await screen.findByRole("heading", { name: "Breath plan" }))
      .closest("article");
    expect(note).not.toBeNull();

    const takeaway = within(note!).getByText("Coaching takeaway");
    const warningSummary = within(note!).getByText("Why might this be wrong?");
    expectToPrecede(takeaway, warningSummary);
    expect(
      within(note!).queryByText("Speaker identity needs human confirmation."),
    ).not.toBeVisible();

    await user.click(warningSummary);

    const warnings = within(note!).getByText("Review these uncertainties");
    expectToPrecede(takeaway, warnings);
    expect(
      within(note!).getByText("Speaker identity needs human confirmation."),
    ).toBeVisible();
    expect(
      within(note!).getByText(/does not prove the coach's point/i),
    ).toBeVisible();
  });

  it("keeps a no-warning note focused on the takeaway before note mechanics", async () => {
    const cleanSession = {
      ...createSession(),
      interventions: [
        {
          ...createSession().interventions[0],
          interpretation:
            "Release the jaw before the tag so the final chord can ring.",
          nextAction: "Sing the tag slowly once, then repeat at tempo.",
          confidence: null,
          uncertaintyReasons: [],
        },
      ],
    };
    const user = userEvent.setup();
    render(<App client={createClient(cleanSession)} />);

    await openFirstRecording(user);
    await user.click(await findShowAllInterventions());
    const note = (await screen.findByRole("heading", { name: "Breath plan" }))
      .closest("article");
    expect(note).not.toBeNull();

    const takeawaySection = within(note!)
      .getByText("Coaching takeaway")
      .closest("section");
    expect(takeawaySection).not.toBeNull();
    const takeaway = within(takeawaySection!).getByText(
      "Release the jaw before the tag so the final chord can ring.",
    );
    expect(
      within(note!).queryByText("Why might this be wrong?"),
    ).not.toBeInTheDocument();
    expectToPrecede(takeaway, within(note!).getByText("Source moments"));
    expectToPrecede(takeaway, within(note!).getByText("Mark this note"));
  });

  it("seeks the audio player when an evidence timestamp is activated", async () => {
    const user = userEvent.setup();
    const client = createClient();
    const play = vi
      .spyOn(HTMLMediaElement.prototype, "play")
      .mockResolvedValue(undefined);
    const { container } = render(<App client={client} />);

    await openFirstRecording(user);
    await user.click(await findShowAllInterventions());
    const evidence = await screen.findByRole("button", {
      name: /play coach feedback at 0:42.*feedback/i,
    });
    const audio = container.querySelector("audio");
    expect(audio).not.toBeNull();
    await user.click(evidence);

    expect(audio!.currentTime).toBe(42);
    expect(play).toHaveBeenCalled();
    await waitFor(() =>
      expect(evidence).toHaveAttribute("aria-pressed", "true"),
    );
    expect(screen.getAllByText(/now playing 0:42/i).length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(
        /source recording jumped to this moment for “Breath plan”/i,
      ).length,
    ).toBeGreaterThan(0);
  });

  it("waits for the audio play promise before showing the active timestamp cue", async () => {
    const user = userEvent.setup();
    const playStarted = deferredPromise<void>();
    vi.spyOn(HTMLMediaElement.prototype, "play").mockReturnValue(
      playStarted.promise,
    );
    const { container } = render(<App client={createClient()} />);

    const { evidence } = await playFirstLedgerMoment(user, container);

    expect(evidence).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText(/now playing 0:42/i)).toBeNull();

    playStarted.resolve();

    await waitFor(() =>
      expect(evidence).toHaveAttribute("aria-pressed", "true"),
    );
    expect(screen.getAllByText(/now playing 0:42/i).length).toBeGreaterThan(0);
  });

  it.each(["pause", "ended", "error"] as const)(
    "clears the active timestamp cue on audio %s",
    async (eventName) => {
      const user = userEvent.setup();
      const play = vi
        .spyOn(HTMLMediaElement.prototype, "play")
        .mockResolvedValue(undefined);
      const { container } = render(<App client={createClient()} />);

      const { audio, evidence } = await playFirstLedgerMoment(user, container);
      fireEvent(audio, new Event("play"));

      expect(play).toHaveBeenCalled();
      expect(evidence).toHaveAttribute("aria-pressed", "true");
      expect(screen.getAllByText(/now playing 0:42/i).length).toBeGreaterThan(0);

      fireEvent(audio, new Event(eventName));

      expect(evidence).toHaveAttribute("aria-pressed", "false");
      expect(screen.queryByText(/now playing 0:42/i)).toBeNull();
    },
  );

  it("clears the active timestamp cue when audio play is rejected", async () => {
    const user = userEvent.setup();
    vi.spyOn(HTMLMediaElement.prototype, "play").mockRejectedValue(
      new DOMException("not allowed", "NotAllowedError"),
    );
    const { container } = render(<App client={createClient()} />);

    const { evidence } = await playFirstLedgerMoment(user, container);

    expect(evidence).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText(/now playing 0:42/i)).toBeNull();
  });

  it("moves the mini playhead from real audio currentTime and duration", async () => {
    const user = userEvent.setup();
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const { container } = render(<App client={createClient()} />);

    const { audio } = await playFirstLedgerMoment(user, container);
    setMediaDuration(audio, 100);
    fireEvent(audio, new Event("loadedmetadata"));
    fireEvent(audio, new Event("play"));
    audio.currentTime = 25;
    fireEvent(audio, new Event("timeupdate"));

    const cue = screen.getAllByText(/now playing 0:42/i)[0].closest(".now-playing-cue");
    const playhead = cue?.querySelector(".now-playing-cue__track span");
    expect(playhead).toHaveStyle({ width: "25%" });

    audio.currentTime = 75;
    fireEvent(audio, new Event("timeupdate"));

    expect(playhead).toHaveStyle({ width: "75%" });
  });

  it("renders an empty mini playhead before audio metadata is available", async () => {
    const user = userEvent.setup();
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const { container } = render(<App client={createClient()} />);

    const { audio } = await playFirstLedgerMoment(user, container);
    setMediaDuration(audio, Number.NaN);
    fireEvent(audio, new Event("play"));

    const cue = screen.getAllByText(/now playing 0:42/i)[0].closest(".now-playing-cue");
    expect(cue?.querySelector(".now-playing-cue__track")).toHaveClass(
      "now-playing-cue__track--empty",
    );
    expect(cue?.querySelector(".now-playing-cue__track span")).toHaveStyle({
      width: "0%",
    });
  });

  it("selecting a second timestamp clears the first cue before showing the second", async () => {
    const user = userEvent.setup();
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const client = createClient();
    vi.mocked(client.getOverview).mockResolvedValue({
      id: "overview-1",
      themes: [
        {
          rank: 1,
          title: "Releasing the sound",
          summary: "The coach worked on timestamp-linked source moments.",
          interventionIds: ["intervention-1"],
          moments: [
            {
              interventionId: "intervention-1",
              startMs: 42_000,
              endMs: 48_000,
            },
            {
              interventionId: "intervention-1",
              startMs: 84_000,
              endMs: 90_000,
            },
          ],
          startMs: 42_000,
          endMs: 90_000,
        },
      ],
      interventionCount: 1,
      stale: false,
      generatedAt: new Date().toISOString(),
    });
    const { container } = render(<App client={client} />);

    await openFirstRecording(user);
    expect(await screen.findByText("Play source moments")).toBeVisible();
    const first = screen.getByRole("button", { name: /play source at 0:42/i });
    const second = screen.getByRole("button", { name: /play source at 1:24/i });
    const audio = container.querySelector("audio");
    expect(audio).not.toBeNull();

    await user.click(first);
    fireEvent(audio!, new Event("play"));
    expect(first).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByText(/now playing 0:42/i).length).toBeGreaterThan(0);

    await user.click(second);
    expect(first).toHaveAttribute("aria-pressed", "false");
    await waitFor(() => expect(second).toHaveAttribute("aria-pressed", "true"));
    expect(screen.queryByText(/now playing 0:42/i)).toBeNull();
    expect(screen.getAllByText(/now playing 1:24/i).length).toBeGreaterThan(0);
  });
});
