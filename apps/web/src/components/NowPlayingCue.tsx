interface NowPlayingCueProps {
  label: string;
  noteTitle: string;
  sourceLabel?: string;
  progressPercent: number | null;
  variant?: "inline" | "section";
}

export function NowPlayingCue({
  label,
  noteTitle,
  sourceLabel,
  progressPercent,
  variant = "inline",
}: NowPlayingCueProps) {
  const clampedProgress =
    progressPercent == null ? null : Math.max(0, Math.min(100, progressPercent));

  return (
    <div
      className={`now-playing-cue now-playing-cue--${variant}`}
      role="status"
    >
      <div className="now-playing-cue__header">
        <span aria-hidden="true">▶</span>
        <strong>Now playing {label}</strong>
      </div>
      <p>Source recording jumped to this moment for “{noteTitle}”.</p>
      {sourceLabel && <p className="now-playing-cue__source">{sourceLabel}</p>}
      <div
        className={`now-playing-cue__track${clampedProgress == null ? " now-playing-cue__track--empty" : ""}`}
        aria-hidden="true"
      >
        <span style={{ width: `${clampedProgress ?? 0}%` }} />
      </div>
    </div>
  );
}
