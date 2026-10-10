import { useEffect, useMemo, useState } from "react";
import { day } from "../lib/format";
import { useT } from "../lib/i18n";
import TimeScrubber from "./TimeScrubber";

export type TLFrame = { key: string; label: string; url: string; sub?: string };

/** A stack of same-place images that cross-fade as the year gauge moves (all images preloaded). */
export default function Timelapse({ frames, aspect = "1 / 1", start = "last", caption, marker }: {
  frames: TLFrame[]; aspect?: string; start?: "first" | "last"; caption?: string; marker?: boolean;
}) {
  const [i, setI] = useState(start === "last" ? Math.max(0, frames.length - 1) : 0);
  useEffect(() => { setI(start === "last" ? Math.max(0, frames.length - 1) : 0); }, [frames.length, start]);
  useEffect(() => { frames.forEach((f) => { const im = new Image(); im.src = f.url; }); }, [frames]);
  if (!frames.length) return null;
  return (
    <figure>
      <div className="relative overflow-hidden rounded-lg border border-line bg-paper-3" style={{ aspectRatio: aspect }}>
        {frames.map((f, k) => (
          <img key={f.key} src={f.url} alt={`${f.label}${f.sub ? `, ${f.sub}` : ""}`} loading={k === i ? "eager" : "lazy"}
            className="absolute inset-0 h-full w-full object-cover transition-opacity duration-500"
            style={{ opacity: k === i ? 1 : 0, imageRendering: "auto" }} />
        ))}
        {marker && (
          <svg viewBox="0 0 40 40" className="pointer-events-none absolute left-1/2 top-1/2 h-10 w-10 -translate-x-1/2 -translate-y-1/2" aria-hidden="true">
            <g stroke="black" strokeOpacity="0.55" strokeWidth="4" strokeLinecap="round"><path d="M20 2v11M20 27v11M2 20h11M27 20h11" /></g>
            <g stroke="white" strokeWidth="2" strokeLinecap="round"><path d="M20 2v11M20 27v11M2 20h11M27 20h11" /></g>
          </svg>
        )}
      </div>
      <div className="mt-3">
        <TimeScrubber labels={frames.map((f) => f.label)} index={i} onChange={setI} sublabel={frames[i]?.sub} compact />
      </div>
      {caption && <figcaption className="muted mt-2 text-[13.5px]">{caption}</figcaption>}
    </figure>
  );
}

export function useLakeFrames(lakeId: string | undefined, seasons: (number | "latest")[] | undefined, latestDate?: string, frameUrls?: Record<string, string>) {
  const { lang } = useT();
  return useMemo<TLFrame[]>(() => {
    if (!lakeId || !seasons) return [];
    return seasons.map((s) => ({
      key: String(s),
      label: s === "latest" ? day(latestDate, lang) : String(s),
      url: frameUrls?.[String(s)] ?? `/pub/lakes/${lakeId}/frames/${s}.webp`,
      sub: s === "latest" ? "Sentinel-2" : Number(s) >= 2016 ? "Sentinel-2" : "Landsat",
    }));
  }, [lakeId, seasons?.join(","), latestDate, lang]);
}
