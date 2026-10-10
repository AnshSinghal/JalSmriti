import * as Slider from "@radix-ui/react-slider";
import { Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useT } from "../lib/i18n";

type Props = {
  labels: string[];                 // one per frame, e.g. ["1990", "1995", ..., "Oct 2026"]
  index: number;
  onChange: (i: number) => void;
  sublabel?: string;                // e.g. "Landsat 5, 26 Dec 1990"
  autoPlayMs?: number;
  compact?: boolean;
};

/** A year gauge modelled on the high-flood-level marks painted on Indian bridges: ticks on a rule, the chosen
 *  year carried by a red flood mark. Keyboard and screen-reader accessible (Radix Slider). */
export default function TimeScrubber({ labels, index, onChange, sublabel, autoPlayMs = 1100, compact }: Props) {
  const { t } = useT();
  const [playing, setPlaying] = useState(false);
  const timer = useRef<number | null>(null);
  const n = labels.length;

  useEffect(() => {
    if (!playing) return;
    timer.current = window.setTimeout(() => {
      if (index >= n - 1) setPlaying(false);
      else onChange(index + 1);
    }, autoPlayMs);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [playing, index, n, autoPlayMs, onChange]);

  if (n === 0) return null;
  return (
    <div className="select-none">
      <div className="flex items-end gap-3">
        <button
          className="tap-sq grid h-10 w-10 shrink-0 place-items-center rounded-full border border-line bg-paper text-ink hover:border-ink-2"
          onClick={() => { if (!playing && index >= n - 1) onChange(0); setPlaying((v) => !v); }}
          aria-label={playing ? t("hero.pause") : t("hero.play")}>
          {playing ? <Pause size={17} /> : <Play size={17} className="translate-x-[1px]" />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <span className={`num leading-none text-ink ${compact ? "text-[1.8rem]" : "text-[2.4rem]"}`} aria-live="polite">{labels[index]}</span>
            {sublabel && <span className="muted truncate text-[13.5px]">{sublabel}</span>}
          </div>
          <Slider.Root className="relative mt-2 flex h-8 w-full touch-none items-center" min={0} max={n - 1} step={1}
            value={[index]} onValueChange={(v) => { setPlaying(false); onChange(v[0]); }} aria-label={t("hero.scrub")}>
            <Slider.Track className="relative h-[2px] w-full grow bg-line">
              <Slider.Range className="absolute h-full bg-ink-2/60" />
            </Slider.Track>
            {labels.map((_, i) => (
              <span key={i} aria-hidden="true"
                className={`pointer-events-none absolute top-1/2 w-px -translate-y-1/2 ${i <= index ? "bg-ink-2" : "bg-line"}`}
                style={{ left: `calc(${(i / Math.max(1, n - 1)) * 100}% )`, height: i % 2 === 0 ? 12 : 8 }} />
            ))}
            <Slider.Thumb className="block h-7 w-[3px] cursor-grab rounded-sm bg-built shadow-[0_0_0_4px_rgb(var(--paper))] outline-none focus-visible:shadow-[0_0_0_4px_rgb(var(--memory)/0.5)] active:cursor-grabbing" />
          </Slider.Root>
          {!compact && (
            <div className="relative h-4 text-[12px] text-ink-2">
              <span className="absolute left-0">{labels[0]}</span>
              <span className="absolute right-0">{labels[n - 1]}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
