import { useState } from "react";
import type {
  CoachingIntervention,
  EvidenceApiClient,
  EvidenceLink,
  SessionDetail,
  VerificationStatus,
} from "@quartet-coach/web-client";
import { evidenceRoleLabel, formatTimestampMs } from "../lib/format";
import { NowPlayingCue } from "./NowPlayingCue";

interface LedgerReviewProps {
  session: SessionDetail;
  client: EvidenceApiClient;
  onSeek: (
    seconds: number,
    moment: {
      key: string;
      label: string;
      noteTitle: string;
      sourceLabel?: string;
    },
  ) => void;
  activeMoment: {
    key: string;
    label: string;
    noteTitle: string;
    sourceLabel?: string;
  } | null;
  playheadPercent: number | null;
  audioAvailable: boolean;
  onUpdated: (session: SessionDetail) => void;
}

export function LedgerReview({
  session,
  client,
  onSeek,
  activeMoment,
  playheadPercent,
  audioAvailable,
  onUpdated,
}: LedgerReviewProps) {
  if (session.interventions.length === 0) {
    return (
      <div className="empty-state">
        <h3>No coaching notes yet</h3>
        <p>Notes appear here after the recording is ready.</p>
      </div>
    );
  }

  return (
    <div className="ledger-list">
      {session.interventions.map((intervention, index) => (
        <InterventionCard
          key={intervention.id}
          sessionId={session.id}
          intervention={intervention}
          index={index}
          client={client}
          onSeek={onSeek}
          activeMoment={activeMoment}
          playheadPercent={playheadPercent}
          audioAvailable={audioAvailable}
          onUpdated={onUpdated}
        />
      ))}
    </div>
  );
}

interface InterventionCardProps {
  sessionId: string;
  intervention: CoachingIntervention;
  index: number;
  client: EvidenceApiClient;
  onSeek: (
    seconds: number,
    moment: {
      key: string;
      label: string;
      noteTitle: string;
      sourceLabel?: string;
    },
  ) => void;
  activeMoment: {
    key: string;
    label: string;
    noteTitle: string;
    sourceLabel?: string;
  } | null;
  playheadPercent: number | null;
  audioAvailable: boolean;
  onUpdated: (session: SessionDetail) => void;
}

function InterventionCard({
  sessionId,
  intervention,
  index,
  client,
  onSeek,
  activeMoment,
  playheadPercent,
  audioAvailable,
  onUpdated,
}: InterventionCardProps) {
  const [choice, setChoice] = useState<"VERIFIED" | "REJECTED" | null>(null);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function saveReview() {
    if (!choice) return;
    setSaving(true);
    setError(null);
    try {
      const updatedSession = await client.reviewIntervention(
        sessionId,
        intervention.id,
        {
          verificationStatus: choice,
          note: note.trim() || null,
        },
      );
      onUpdated(updatedSession);
      setChoice(null);
      setNote("");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Review could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  const confidence =
    intervention.confidence == null
      ? null
      : Math.round(Math.max(0, Math.min(1, intervention.confidence)) * 100);

  return (
    <article
      className={`ledger-card${intervention.evidence.some((evidence) => activeMoment?.key === evidence.id) ? " ledger-card--active" : ""}`}
      aria-labelledby={`intervention-${intervention.id}`}
    >
      <div className="ledger-card__heading">
        <div>
          <p className="eyebrow">Note {index + 1}</p>
          <h3 id={`intervention-${intervention.id}`}>
            {intervention.topic || "Coaching note"}
          </h3>
        </div>
        <VerificationBadge status={intervention.verificationStatus} />
      </div>

      {confidence != null && (
        <details className="note-details">
          <summary>How sure is the assistant about this note?</summary>
          <div className="confidence-panel">
            <strong>{confidence}%</strong>
            <meter
              min="0"
              max="100"
              low={60}
              high={80}
              optimum={100}
              value={confidence}
            >
              {confidence}%
            </meter>
            <p>
              This number is only about how clearly the assistant found the note
              in the transcript. It does not prove the coach's point or the
              musical result.
            </p>
          </div>
        </details>
      )}

      {intervention.uncertaintyReasons.length > 0 && (
        <div className="uncertainty-box">
          <strong>Review these uncertainties</strong>
          <ul>
            {intervention.uncertaintyReasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="ledger-grid">
        <LedgerField
          label="Coach's exact words"
          value={intervention.exactCoachFeedback}
          quote
        />
        <LedgerField
          label="Plain-language meaning"
          value={intervention.interpretation}
        />
        <LedgerField label="Who it applies to" value={intervention.appliesTo} />
        <LedgerField
          label="Song or passage"
          value={intervention.songReference}
        />
        <LedgerField
          label="What the coach heard before"
          value={intervention.problemBefore}
        />
        <LedgerField
          label="What the coach asked us to try"
          value={intervention.exerciseOrRequestedChange}
        />
        <LedgerField
          label="What happened after we tried it"
          value={intervention.observedResult}
        />
        <LedgerField label="Next step" value={intervention.nextAction} />
        <LedgerField
          label="Question to check"
          value={intervention.unresolvedQuestion}
        />
      </div>

      <div className="evidence-section">
        <span className="field-label">Source moments</span>
        {intervention.evidence.length === 0 ? (
          <p className="missing-value">No timestamped source was supplied.</p>
        ) : (
          <ul className="evidence-links">
            {intervention.evidence.map((evidence) => (
              <EvidenceButton
                key={evidence.id}
                evidence={evidence}
                noteTitle={intervention.topic || `Note ${index + 1}`}
                active={activeMoment?.key === evidence.id}
                enabled={audioAvailable}
                onSeek={onSeek}
              />
            ))}
          </ul>
        )}
        {activeMoment &&
          intervention.evidence.some(
            (evidence) => activeMoment.key === evidence.id,
          ) && (
            <NowPlayingCue
              label={activeMoment.label}
              noteTitle={activeMoment.noteTitle}
              sourceLabel={activeMoment.sourceLabel}
              progressPercent={playheadPercent}
            />
          )}
      </div>

      <fieldset className="review-controls">
        <legend>Mark this note</legend>
        <div className="segmented-control">
          {(["VERIFIED", "REJECTED"] as const).map((status) => (
            <label key={status}>
              <input
                type="radio"
                name={`review-${intervention.id}`}
                value={status}
                checked={choice === status}
                onChange={() => setChoice(status)}
                disabled={saving}
              />
              {status === "VERIFIED" ? "Looks right" : "Needs correction"}
            </label>
          ))}
        </div>
        <label>
          Your note <span className="optional">(optional)</span>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={3}
            disabled={saving}
          />
          <span className="supporting-text">
            If the transcript itself is wrong, fix it in the transcript editor
            and then check for transcript updates from Recording options.
          </span>
        </label>
        {error && (
          <div className="inline-alert inline-alert--danger" role="alert">
            {error}
          </div>
        )}
        <button
          className="button button--primary"
          onClick={saveReview}
          disabled={!choice || saving}
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </fieldset>
    </article>
  );
}

function LedgerField({
  label,
  value,
  quote = false,
}: {
  label: string;
  value: string | null;
  quote?: boolean;
}) {
  return (
    <div className="ledger-field">
      <span className="field-label">{label}</span>
      {value ? (
        quote ? (
          <blockquote>{value}</blockquote>
        ) : (
          <p>{value}</p>
        )
      ) : (
        <p className="missing-value">
          {quote ? "No exact quote was captured." : "Not mentioned."}
        </p>
      )}
    </div>
  );
}

function EvidenceButton({
  evidence,
  noteTitle,
  active,
  enabled,
  onSeek,
}: {
  evidence: EvidenceLink;
  noteTitle: string;
  active: boolean;
  enabled: boolean;
  onSeek: (
    seconds: number,
    moment: {
      key: string;
      label: string;
      noteTitle: string;
      sourceLabel?: string;
    },
  ) => void;
}) {
  const label = formatTimestampMs(evidence.startMs);
  const role = evidenceRoleLabel(evidence.role).toLowerCase();
  return (
    <li>
      <button
        className={`evidence-link evidence-link--play${active ? " evidence-link--active" : ""}`}
        aria-pressed={active}
        onClick={() =>
          onSeek(evidence.startMs / 1000, {
            key: evidence.id,
            label,
            noteTitle,
            sourceLabel: evidence.label,
          })
        }
        disabled={!enabled}
        title={
          enabled
            ? "Play the recording from this moment"
            : "Audio is unavailable"
        }
      >
        <span aria-hidden="true">▶</span>
        <strong>
          {active ? "Now playing" : "Play"} {role} at {label}
        </strong>
        <span>{evidence.label}</span>
      </button>
    </li>
  );
}

function VerificationBadge({ status }: { status: VerificationStatus }) {
  return (
    <span className={`verification verification--${status.toLowerCase()}`}>
      {status === "UNVERIFIED"
        ? "Not checked"
        : status === "NEEDS_REVIEW"
          ? "Check again"
          : status === "VERIFIED"
            ? "Checked"
            : "Needs correction"}
    </span>
  );
}
