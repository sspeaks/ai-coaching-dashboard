import { render, screen, waitFor } from "@testing-library/react";
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
  await user.click(await screen.findByRole("button", { name: /read feedback/i }));
  return user;
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
    ["/", "Hear what the coach worked on."],
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
      screen.queryByRole("button", { name: "Upload a recording" }),
    ).toBeNull();
    await user.click(screen.getByRole("link", { name: "Upload" }));
    expect(
      screen.getByText(/sent to Speakr for transcription/i),
    ).toBeVisible();
    const disclosure = screen.getByRole("button", {
      name: /what happens to my recording/i,
    });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
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
    await user.click(screen.getByRole("button", { name: "Upload recording" }));

    await waitFor(() =>
      expect(client.completeUpload).toHaveBeenCalledWith(
        "uploaded-session",
        "upload-1",
      ),
    );
    expect(await screen.findByText(/Practice upload was uploaded/i)).toBeVisible();
  });

  it("keeps recording management off the feedback page", async () => {
    const user = userEvent.setup();
    const client = createClient();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<App client={client} />);

    await screen.findByText("Choose a coaching session");
    expect(screen.queryByRole("button", { name: /delete recording/i })).toBeNull();
    await user.click(screen.getByRole("link", { name: "Manage recordings" }));
    expect(await screen.findByText("Recording controls")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /delete recording/i }));

    await waitFor(() =>
      expect(client.deleteSession).toHaveBeenCalledWith("session-1"),
    );
  });

  it("opens the newest session summary on the feedback page", async () => {
    const client = createClient();
    render(<App client={client} />);

    // The dense ledger is a drill-down; the headline items are what a singer
    // should land on after a rehearsal.
    expect(await screen.findByText("Releasing the sound")).toBeVisible();
    expect(
      screen.getByText(/releasing jaw tension on the F/i),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: /0:42/ })).toBeVisible();
    expect(
      screen.queryByText("Speaker identity needs human confirmation."),
    ).toBeNull();
  });

  it("does not auto-open anything when there are no sessions", async () => {
    const client = createClient();
    vi.mocked(client.listSessions).mockResolvedValue([]);
    render(<App client={client} />);

    expect(await screen.findByText("No feedback yet")).toBeVisible();
    expect(screen.getByText(/There are no coaching summaries yet/i)).toBeVisible();
    expect(client.getSession).not.toHaveBeenCalled();
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
    const older = { ...createSession(), id: "older-session", title: "Older take" };
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
    expect(await screen.findByText("Coaching notes are not ready yet")).toBeVisible();
    expect(client.getSession).toHaveBeenCalledWith(
      "processing-session",
      expect.any(AbortSignal),
    );
  });

  it("auto-opens the newest failed session", async () => {
    const failed = {
      ...createSession(),
      id: "failed-session",
      title: "Newest failed take",
      state: "FAILED" as const,
      error: { message: "Speakr could not read the file.", retryable: true },
      interventions: [],
      interventionCount: 0,
    };
    const older = { ...createSession(), id: "older-session", title: "Older take" };
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
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "We could not finish this recording. Speakr could not read the file.",
      ),
    );
    expect(client.getSession).toHaveBeenCalledWith(
      "failed-session",
      expect.any(AbortSignal),
    );
  });

  it("shows a plain-language page for unknown URLs", async () => {
    const user = userEvent.setup();
    const client = createClient();
    window.history.pushState({}, "", "/not-a-real-page");
    render(<App client={client} />);

    expect(await screen.findByText("This page does not exist.")).toBeVisible();
    expect(screen.getByText(/go back to the feedback list/i)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Back to feedback" }));
    expect(await screen.findByText("Hear what the coach worked on.")).toBeVisible();
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
    expect(await screen.findByText(/summary may be out of date/i)).toBeVisible();
  });

  it("shows uncertainty and saves a human verification decision", async () => {
    const user = userEvent.setup();
    const client = createClient();
    render(<App client={client} />);

    await openFirstRecording(user);
    await user.click(await findShowAllInterventions());
    expect(await screen.findByText("Speaker identity needs human confirmation.")).toBeVisible();
    await user.click(screen.getByText(/how sure is the assistant about this note/i));
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
      name: /coach feedback.*0:42.*feedback/i,
    });
    const audio = container.querySelector("audio");
    expect(audio).not.toBeNull();
    await user.click(evidence);

    expect(audio!.currentTime).toBe(42);
    expect(play).toHaveBeenCalled();
  });
});
