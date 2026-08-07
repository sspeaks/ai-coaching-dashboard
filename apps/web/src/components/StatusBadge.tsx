import {
  isActiveSessionState,
  isFailedSessionState,
  type SessionState,
} from "@quartet-coach/web-client";
import { stateLabel } from "../lib/format";

export function StatusBadge({ state }: { state: SessionState }) {
  const tone = isFailedSessionState(state)
    ? "danger"
    : state === "COMPLETE"
      ? "success"
      : state === "AWAITING_REVIEW"
        ? "attention"
        : isActiveSessionState(state)
          ? "active"
          : "neutral";
  return (
    <span className={`status-badge status-badge--${tone}`}>
      <span className="status-badge__dot" aria-hidden="true" />
      {stateLabel(state)}
    </span>
  );
}
