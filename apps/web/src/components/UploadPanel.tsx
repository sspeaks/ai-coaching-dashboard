import { useRef, useState, type DragEvent, type FormEvent } from "react";
import type { EvidenceApiClient, SessionDetail } from "@quartet-coach/web-client";

interface UploadPanelProps {
  client: EvidenceApiClient;
  onUploaded: (session: SessionDetail) => void;
}

export function UploadPanel({ client, onUploaded }: UploadPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadedMessage, setUploadedMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [disclosureOpen, setDisclosureOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  function chooseFile(nextFile: File | null) {
    setFile(nextFile);
    setError(null);
    setUploadedMessage(null);
  }

  function handleDrag(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    if (!uploading) {
      setDragging(true);
    }
  }

  function handleDragLeave(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    if (uploading) return;
    chooseFile(event.dataTransfer.files?.[0] ?? null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || file.size === 0) {
      setError("Choose a non-empty recording to upload.");
      return;
    }

    setError(null);
    setUploading(true);
    setProgress(0);
    const controller = new AbortController();
    abortRef.current = controller;
    let sessionId: string | null = null;
    try {
      setUploadedMessage(null);
      const ticket = await client.initiateUpload({
        fileName: file.name,
        contentType: file.type || "application/octet-stream",
        sizeBytes: file.size,
        title: title.trim() || undefined,
      });
      sessionId = ticket.session.id;
      await client.uploadFile(
        ticket.upload,
        file,
        setProgress,
        controller.signal,
      );
      const session = await client.completeUpload(
        ticket.session.id,
        ticket.upload.id,
      );
      setFile(null);
      setTitle("");
      setProgress(null);
      setUploadedMessage(
        `${session.title} was uploaded. We are listening to it now; check this page for updates.`,
      );
      onUploaded(session);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        if (sessionId) {
          await client.cancelSession(sessionId).catch(() => undefined);
        }
        setError("Upload cancelled.");
      } else {
        setError(caught instanceof Error ? caught.message : "Upload failed.");
      }
    } finally {
      abortRef.current = null;
      setUploading(false);
    }
  }

  return (
    <section className="panel upload-panel" aria-labelledby="upload-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Step 1</p>
          <h2 id="upload-heading">Upload a coaching recording</h2>
        </div>
      </div>
      <form onSubmit={submit}>
        <label>
          Recording name <span className="optional">(optional)</span>
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            disabled={uploading}
            placeholder="August coaching"
            aria-describedby="recording-name-hint"
          />
          <span id="recording-name-hint" className="field-hint">
            Example: August coaching with Alex
          </span>
        </label>
        <label
          className={`upload-dropzone${dragging ? " upload-dropzone--active" : ""}${file ? " upload-dropzone--selected" : ""}`}
          onDragEnter={handleDrag}
          onDragOver={handleDrag}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <span>Audio file</span>
          <span className="upload-dropzone__prompt">
            {dragging
              ? "Drop the recording here"
              : file
                ? `${file.name} selected`
                : "Drag an audio file here or choose a file"}
          </span>
          <span className="upload-dropzone__hint">
            MP3, WAV, M4A, FLAC, AAC, OGG, OPUS, or MP4 audio.
          </span>
          <input
            type="file"
            aria-label="Audio file"
            accept="audio/*,.m4a,.mp3,.wav,.flac,.aac,.ogg,.opus,.mp4"
            onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
            disabled={uploading}
          />
        </label>
        <p className="supporting-text">
          Audio files such as MP3, WAV, M4A, FLAC, AAC, OGG, and OPUS are
          accepted. Keep this page open until the upload finishes.
        </p>
        <div className="privacy-disclosure">
          <p className="privacy-disclosure__intro">
            Before you upload, make sure everyone on the recording is okay with
            these processing steps:
          </p>
          <ul className="privacy-disclosure__facts">
            <li>
              <strong>Audio is stored here.</strong> The dashboard saves the
              uploaded recording so it can be processed and played back.
            </li>
            <li>
              <strong>Audio is sent for transcription.</strong> The recording
              goes through the configured Speakr/transcription path, which may
              use a downstream ASR provider.
            </li>
            <li>
              <strong>Text may be analyzed by AI.</strong> When enabled,
              transcript text and coaching-note text may be sent to the
              configured AI extraction gateway.
            </li>
            <li>
              <strong>Deletion is explicit.</strong> Recordings and notes stay
              until an admin deletes them or operator retention tooling removes
              them.
            </li>
          </ul>
          <button
            className="disclosure-button"
            type="button"
            aria-expanded={disclosureOpen}
            aria-controls="upload-privacy-details"
            onClick={() => setDisclosureOpen((isOpen) => !isOpen)}
          >
            What happens to my recording?
          </button>
          <div id="upload-privacy-details" hidden={!disclosureOpen}>
            <p>
              Your audio is saved on this dashboard&apos;s server so you can
              play it back. The original file is kept until an admin deletes
              the recording; this app does not automatically expire it.
            </p>
            <p>
              To transcribe it, this dashboard sends the audio to Speakr. In
              the documented deployment, Speakr uses OpenAI for transcription;
              other deployments may use a self-hosted transcription service
              instead.
            </p>
            <p>
              If AI note extraction is turned on, transcript text and note text
              are sent to the configured AI extraction service, which may use
              OpenAI or another OpenAI-compatible provider.
            </p>
            <p>
              When an admin confirms deletion, this dashboard removes the saved
              audio file and dashboard record, and deletion does not finish
              unless the Speakr copy is deleted too. Audio or text already sent
              to other transcription or AI providers may not be removable by
              this dashboard.
            </p>
          </div>
        </div>
        {progress !== null && (
          <div className="upload-progress" aria-live="polite">
            <div className="progress-row">
              <span>Uploading {file?.name}</span>
              <strong>{progress}%</strong>
            </div>
            <progress value={progress} max="100">
              {progress}%
            </progress>
          </div>
        )}
        {error && (
          <div className="inline-alert inline-alert--danger" role="alert">
            {error}
          </div>
        )}
        {uploadedMessage && (
          <div className="inline-alert inline-alert--success" role="status">
            {uploadedMessage}
          </div>
        )}
        <div className="button-row">
          <button className="button button--primary" disabled={!file || uploading}>
            {uploading ? "Uploading…" : "Upload recording"}
          </button>
          {uploading && (
            <button
              className="button button--quiet"
              type="button"
              onClick={() => abortRef.current?.abort()}
            >
              Cancel upload
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
