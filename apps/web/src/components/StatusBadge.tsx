import type { SessionState } from "@quartet-coach/web-client";
import { sessionStatus } from "../lib/format";

export function StatusBadge({ state }: { state: SessionState }) {
  const status = sessionStatus(state);
  return (
    <span className={`status-badge status-badge--${status.tone}`}>
      <span className="status-badge__dot" aria-hidden="true" />
      {status.label}
    </span>
  );
}
