import { useState } from "react";
import type {
  CoachingIntervention,
  EvidenceApiClient,
  EvidenceLink,
  SessionDetail,
  VerificationStatus,
} from "@quartet-coach/web-client";
import { evidenceRoleLabel, formatTimestampMs } from "../lib/format";

interface LedgerReviewProps {
  session: SessionDetail;
  client: EvidenceApiClient;
  onSeek: (seconds: number) => void;
  audioAvailable: boolean;
  onUpdated: (session: SessionDetail) => void;
}

export function LedgerReview({
  session,
  client,
  onSeek,
  audioAvailable,
  onUpdated,
}: LedgerReviewProps) {
  if (session.interventions.length === 0) {
    return (
      <div className="empty-state">
        <h3>No ledger entries available</h3>
        <p>
          Entries appear after transcript processing and evidence extraction.
          Transcript corrections remain in Speakr.
        </p>
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
  onSeek: (seconds: number) => void;
  audioAvailable: boolean;
  onUpdated: (session: SessionDetail) => void;
}

function InterventionCard({
  sessionId,
  intervention,
  index,
  client,
  onSeek,
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
      setError(caught instanceof Error ? caught.message : "Review could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  const confidence =
    intervention.confidence == null
      ? null
      : Math.round(Math.max(0, Math.min(1, intervention.confidence)) * 100);

  return (
    <article className="ledger-card" aria-labelledby={`intervention-${intervention.id}`}>
      <div className="ledger-card__heading">
        <div>
          <p className="eyebrow">Intervention {index + 1}</p>
          <h3 id={`intervention-${intervention.id}`}>
            {intervention.topic || "Untitled coaching intervention"}
          </h3>
        </div>
        <VerificationBadge status={intervention.verificationStatus} />
      </div>

      <div className="confidence-panel">
        <div>
          <span className="field-label">Extraction confidence</span>
          <strong>{confidence == null ? "Not available" : `${confidence}%`}</strong>
        </div>
        {confidence != null && (
          <meter min="0" max="100" low={60} high={80} optimum={100} value={confidence}>
            {confidence}%
          </meter>
        )}
        <p>
          Confidence reflects extraction certainty, not whether the coaching
          statement or a musical outcome is correct.
        </p>
      </div>

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
          label="Exact coach feedback"
          value={intervention.exactCoachFeedback}
          quote
        />
        <LedgerField label="Interpretation" value={intervention.interpretation} />
        <LedgerField label="Applies to" value={intervention.appliesTo} />
        <LedgerField label="Song or passage" value={intervention.songReference} />
        <LedgerField label="Problem heard before" value={intervention.problemBefore} />
        <LedgerField
          label="Exercise or requested change"
          value={intervention.exerciseOrRequestedChange}
        />
        <LedgerField label="Observed result" value={intervention.observedResult} />
        <LedgerField label="Next action" value={intervention.nextAction} />
        <LedgerField
          label="Unresolved question"
          value={intervention.unresolvedQuestion}
        />
      </div>

      <div className="evidence-section">
        <span className="field-label">Source evidence</span>
        {intervention.evidence.length === 0 ? (
          <p className="missing-value">No timestamped evidence was supplied.</p>
        ) : (
          <ul className="evidence-links">
            {intervention.evidence.map((evidence) => (
              <EvidenceButton
                key={evidence.id}
                evidence={evidence}
                enabled={audioAvailable}
                onSeek={onSeek}
              />
            ))}
          </ul>
        )}
      </div>

      <fieldset className="review-controls">
        <legend>Human review</legend>
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
              {status === "VERIFIED" ? "Verify" : "Reject"}
            </label>
          ))}
        </div>
        <label>
          Review note <span className="optional">(optional)</span>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={3}
            disabled={saving}
          />
          <span className="supporting-text">
            Edit transcript text in Speakr, then use “Refresh from Speakr” to
            preserve and import a new revision.
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
          {saving ? "Saving…" : "Save review"}
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
        <p className="missing-value">Not provided</p>
      )}
    </div>
  );
}

function EvidenceButton({
  evidence,
  enabled,
  onSeek,
}: {
  evidence: EvidenceLink;
  enabled: boolean;
  onSeek: (seconds: number) => void;
}) {
  return (
    <li>
      <button
        className="evidence-link"
        onClick={() => onSeek(evidence.startMs / 1000)}
        disabled={!enabled}
        title={enabled ? "Seek recording to this evidence" : "Audio is unavailable"}
      >
        <span>{evidenceRoleLabel(evidence.role)}</span>
        <strong>{formatTimestampMs(evidence.startMs)}</strong>
        <span>{evidence.label}</span>
      </button>
    </li>
  );
}

function VerificationBadge({ status }: { status: VerificationStatus }) {
  return (
    <span className={`verification verification--${status.toLowerCase()}`}>
      {status === "UNVERIFIED"
        ? "Needs review"
        : status === "NEEDS_REVIEW"
          ? "Needs re-review"
        : status.charAt(0) + status.slice(1).toLowerCase()}
    </span>
  );
}
