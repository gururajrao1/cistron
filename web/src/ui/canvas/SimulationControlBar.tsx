import { clsx, tw } from "../design_system";

export type SimulationControlBarProps = {
  t: number;
  tStart: number;
  tEnd: number;
  playing: boolean;
  onTogglePlay: () => void;
  onSeek: (t: number) => void;
  onReset: () => void;
};

/**
 * Video-style play / pause / scrubber for pathway animation frames.
 */
export function SimulationControlBar({
  t,
  tStart,
  tEnd,
  playing,
  onTogglePlay,
  onSeek,
  onReset,
}: SimulationControlBarProps) {
  const span = Math.max(1e-6, tEnd - tStart);
  const pct = ((t - tStart) / span) * 100;

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-[10px] border border-[rgba(0,229,255,0.28)] bg-[rgba(17,24,39,0.72)] px-3 py-2 backdrop-blur-[16px]">
      <button type="button" className={tw.btnPrimary} onClick={onTogglePlay} aria-label={playing ? "Pause" : "Play"}>
        {playing ? "Pause" : "Play"}
      </button>
      <button type="button" className={tw.btnGhost} onClick={onReset}>
        Rewind
      </button>
      <div className="min-w-[180px] flex-1">
        <input
          type="range"
          min={tStart}
          max={tEnd}
          step={span / 200}
          value={t}
          onChange={(e) => onSeek(Number(e.target.value))}
          className="vs-slider w-full"
          aria-label="Simulation timeline scrubber"
          style={{
            background: `linear-gradient(to right, #00E5FF 0%, #00E5FF ${pct}%, #1E293B ${pct}%, #1E293B 100%)`,
          }}
        />
      </div>
      <span className={clsx(tw.mono, "tabular-nums text-[#00E5FF]")}>
        t = {t.toFixed(2)} / {tEnd.toFixed(1)}
      </span>
    </div>
  );
}
