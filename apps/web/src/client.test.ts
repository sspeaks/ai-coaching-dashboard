import { describe, expect, it, vi } from "vitest";
import {
  ApiError,
  createHttpEvidenceApiClient,
  type EvidenceApiLedgerEntry,
  type EvidenceApiSession,
} from "@quartet-coach/web-client";

const apiSession: EvidenceApiSession = {
  id: "session-1",
  title: "Contract session",
  state: "AWAITING_REVIEW",
  recorded_at: null,
  duration_ms: 180_000,
  original_filename: "recording.wav",
  media_sha256: "a".repeat(64),
  speakr_recording_id: "recording-1",
  current_transcript_revision_id: "revision-1",
  last_reconciled_at: "2026-08-07T01:00:00Z",
  last_error: null,
  playback_url: "/api/sessions/session-1/media",
  ledger_entry_count: 1,
  reviewed_ledger_entry_count: 0,
  created_at: "2026-08-07T00:00:00Z",
  updated_at: "2026-08-07T01:00:00Z",
};

const apiLedgerEntry: EvidenceApiLedgerEntry = {
  id: "entry-1",
  session_id: "session-1",
  transcript_revision_id: "revision-1",
  topic: "Release",
  exact_coach_feedback: "Release the sound.",
  interpretation: null,
  applies_to: null,
  song_passage_measure: null,
  problem_heard_before: null,
  exercise_or_requested_change: null,
  observed_result: null,
  next_action_and_owner: null,
  unresolved_question: null,
  confidence: 0.9,
  evidence: [
    {
      transcript_revision_id: "revision-1",
      start_ms: 1_250,
      end_ms: 2_500,
      segment_ids: ["segment-1"],
    },
  ],
  extraction_metadata: {
    uncertainty_reasons: ["Confirm the speaker with a human reviewer."],
  },
  verification_status: "UNVERIFIED",
  verified_by: null,
  verified_at: null,
  created_at: "2026-08-07T01:00:00Z",
  updated_at: "2026-08-07T01:00:00Z",
};

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HTTP evidence API client", () => {
  it("uses the configured base URL and same-origin credentials", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = createHttpEvidenceApiClient({
      baseUrl: "/evidence-api/",
      fetch: fetcher,
    });

    await client.listSessions();

    expect(fetcher).toHaveBeenCalledWith(
      "/evidence-api/sessions",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("reads the current authenticated user from the backend", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        subject: "reverie@example.com",
        username: "reverie",
        role: "admin",
      }),
    );
    const client = createHttpEvidenceApiClient({ fetch: fetcher });

    await expect(client.getCurrentUser()).resolves.toEqual({
      subject: "reverie@example.com",
      username: "reverie",
      role: "admin",
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/me",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("surfaces an authentication failure without exposing response details", async () => {
    const client = createHttpEvidenceApiClient({
      fetch: vi.fn<typeof fetch>().mockResolvedValue(
        new Response(JSON.stringify({ detail: "proxy response" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    });

    await expect(client.listSessions()).rejects.toMatchObject({
      status: 401,
      message: "Your session has expired. Sign in again.",
    } satisfies Partial<ApiError>);
  });

  it("maps the backend session, millisecond evidence, playback, and ledger contract", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/api/sessions/session-1") return jsonResponse(apiSession);
      if (url === "/api/sessions/session-1/ledger") {
        return jsonResponse([apiLedgerEntry]);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    const client = createHttpEvidenceApiClient({ fetch: fetcher });

    const detail = await client.getSession("session-1");

    expect(detail).toMatchObject({
      durationMs: 180_000,
      audioUrl: "/api/sessions/session-1/media",
      interventionCount: 1,
      interventions: [
        {
          id: "entry-1",
          verificationStatus: "UNVERIFIED",
          evidence: [{ startMs: 1_250, endMs: 2_500 }],
        },
      ],
    });
  });

  it("uses the concrete create, multipart upload, refresh, review, cancel, and deletion routes", async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      calls.push({ url, init });
      if (url.endsWith("/ledger")) return jsonResponse([apiLedgerEntry]);
      if (url.endsWith("/deletion/confirm")) {
        return new Response(null, { status: 204 });
      }
      if (url.endsWith("/verification")) return jsonResponse(apiLedgerEntry);
      return jsonResponse(apiSession, init?.method === "POST" && url === "/api/sessions" ? 201 : 200);
    });
    const client = createHttpEvidenceApiClient({ fetch: fetcher });

    const ticket = await client.initiateUpload({
      fileName: "recording.wav",
      contentType: "audio/wav",
      sizeBytes: 5,
      title: "Contract session",
    });
    expect(ticket.upload).toEqual({
      url: "/api/sessions/session-1/media",
      method: "POST",
      fileFieldName: "media",
    });

    await client.refreshFromSpeakr("session-1");
    await client.reviewIntervention("session-1", "entry-1", {
      verificationStatus: "VERIFIED",
      note: "Checked against the recording.",
    });
    await client.cancelSession("session-1");
    await client.deleteSession("session-1");

    expect(calls.map((call) => [call.init?.method ?? "GET", call.url])).toEqual(
      expect.arrayContaining([
        ["POST", "/api/sessions"],
        ["POST", "/api/sessions/session-1/refresh"],
        ["PUT", "/api/ledger/entry-1/verification"],
        ["POST", "/api/sessions/session-1/cancel"],
        ["DELETE", "/api/sessions/session-1"],
        ["POST", "/api/sessions/session-1/deletion/confirm"],
      ]),
    );
    const confirmation = calls.find((call) =>
      call.url.endsWith("/deletion/confirm"),
    );
    expect(confirmation?.init?.body).toBe(
      JSON.stringify({ confirm_session_id: "session-1" }),
    );
  });

  it("posts the recording as multipart field media to the backend upload route", async () => {
    class FakeXhr {
      static latest: FakeXhr;
      status = 200;
      method = "";
      url = "";
      body: Document | XMLHttpRequestBodyInit | null = null;
      listeners = new Map<string, EventListener>();
      upload = {
        addEventListener: vi.fn(),
      };

      constructor() {
        FakeXhr.latest = this;
      }

      open(method: string, url: string) {
        this.method = method;
        this.url = url;
      }

      setRequestHeader() {}

      addEventListener(name: string, listener: EventListener) {
        this.listeners.set(name, listener);
      }

      send(body: Document | XMLHttpRequestBodyInit | null) {
        this.body = body;
        this.listeners.get("load")?.(new Event("load"));
      }

      abort() {
        this.listeners.get("abort")?.(new Event("abort"));
      }
    }
    vi.stubGlobal(
      "XMLHttpRequest",
      FakeXhr as unknown as typeof XMLHttpRequest,
    );
    const client = createHttpEvidenceApiClient();
    const progress = vi.fn();
    const file = new File(["audio"], "recording.wav", { type: "audio/wav" });

    await client.uploadFile(
      {
        url: "/api/sessions/session-1/media",
        method: "POST",
        fileFieldName: "media",
      },
      file,
      progress,
    );

    expect(FakeXhr.latest.method).toBe("POST");
    expect(FakeXhr.latest.url).toBe("/api/sessions/session-1/media");
    expect(FakeXhr.latest.body).toBeInstanceOf(FormData);
    expect((FakeXhr.latest.body as FormData).get("media")).toBe(file);
    expect(progress).toHaveBeenLastCalledWith(100);
    vi.unstubAllGlobals();
  });
});
