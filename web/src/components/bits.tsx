import { AlertTriangle, CircleDot, Info, Loader2, Radar } from "lucide-react";
import type { ReactNode } from "react";
import { day, gradeColor, ha } from "../lib/format";
import { useT } from "../lib/i18n";
import type { Finding, SeasonPoint } from "../lib/types";

/** Grade as a flood-mark plate: thick bars above and below, like painted HFL markers. */
export function GradePlate({ grade, size = "md" }: { grade?: string | null; size?: "sm" | "md" | "lg" }) {
  const { t } = useT();
  const fs = size === "lg" ? "text-[2.6rem]" : size === "sm" ? "text-[1.05rem]" : "text-[1.6rem]";
  const label = grade ? t(`grade.${grade}` as any) : t("grade.none");
  return (
    <span className={`plate ${fs}`} style={{ color: gradeColor(grade) }} title={label} aria-label={`${t("lake.grade")}: ${grade ?? "-"}, ${label}`}>
      {grade ?? "–"}
    </span>
  );
}

export function Stat({ label, value, unit, note, tone }: { label: string; value: ReactNode; unit?: string; note?: ReactNode; tone?: "lost" | "built" | "memory" }) {
  const color = tone === "lost" ? "text-lost" : tone === "built" ? "text-built" : tone === "memory" ? "text-memory" : "text-ink";
  return (
    <div className="min-w-0">
      <div className="muted text-[14px] leading-tight">{label}</div>
      <div className={`num mt-1 text-[2rem] leading-none ${color}`}>
        {value}{unit && <span className="ml-1 text-[1rem] font-semibold text-ink-2">{unit}</span>}
      </div>
      {note && <div className="muted mt-1 text-[13px] leading-snug">{note}</div>}
    </div>
  );
}

/** Translate a finding from its key and numbers; fall back to the English text from the API. */
export function useFindingText() {
  const { t, lang } = useT();
  return (f: Finding): string => {
    if (!f.vars) return f.text;          // records made before findings carried their numbers
    const v = f.vars;
    const key = `f.${f.key}` as any;
    if (f.key === "lost") {
      let s = t("f.lost", { lostHa: ha(v.lostHa), lostPct: Math.round(v.lostPct ?? 0) });
      const now = Object.entries((v.now ?? {}) as Record<string, number>).map(([k, n]) => t(`lc.${k}` as any, { ha: ha(n) }));
      if (now.length) s += " " + t("f.lostNow", { list: now.join(", ") });
      if (v.again >= 0.3) s += " " + t("f.lostAgain", { again: ha(v.again) });
      return s;
    }
    const out = t(key, Object.fromEntries(Object.entries(v).map(([k, x]) => [k, typeof x === "number" ? ha(x) : k === "date" ? day(String(x), lang) : String(x)])));
    return out === key ? f.text : out;
  };
}

export function FindingList({ findings }: { findings: Finding[] }) {
  const text = useFindingText();
  return (
    <ul className="divide-y divide-line">
      {findings.map((f, i) => (
        <li key={i} className="flex gap-3 py-3">
          <span className="mt-1 shrink-0" aria-hidden="true">
            {f.key === "radar" ? <Radar size={18} className="text-built" /> :
              f.severity === "high" ? <AlertTriangle size={18} className="text-built" /> :
              f.severity === "medium" ? <CircleDot size={18} className="text-lost" /> :
              <Info size={18} className="text-ink-2" />}
          </span>
          <span className="text-[16px] leading-snug">{text(f)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Post-monsoon water spread per season: Landsat (1987-2015) and Sentinel-2 (2016 on) bars, the historic spread
 *  as a red flood mark, monsoon rain as small dots on its own scale. Plain SVG, no chart library. */
export function SeriesChart({ series, historicHa, height = 190 }: { series: SeasonPoint[]; historicHa: number; height?: number }) {
  const { t } = useT();
  if (!series.length) return null;
  const first = 1987, last = Math.max(...series.map((s) => s.season), 2025);
  const n = last - first + 1;
  const W = 720, H = height, padL = 34, padB = 22, padT = 14;
  const top = Math.max(historicHa, ...series.map((s) => s.waterHa)) * 1.08 || 1;
  const bw = (W - padL) / n;
  const y = (v: number) => padT + (H - padT - padB) * (1 - v / top);
  const rains = series.filter((s) => s.rainMm).map((s) => s.rainMm as number);
  const rmax = rains.length ? Math.max(...rains) * 1.05 : 1;
  const ry = (v: number) => padT + (H - padT - padB) * (1 - v / rmax);
  const by = new Map(series.map((s) => [s.season, s]));
  const ticks = [0, top / 2, top].map((v) => Math.round(v));
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
        aria-label={`${t("lake.series")}: ${series.length} seasons, ${first} to ${last}`}>
        {ticks.map((v, i) => (
          <g key={i}>
            <line x1={padL} x2={W} y1={y(v)} y2={y(v)} stroke="rgb(var(--line))" strokeWidth={1} />
            <text x={padL - 6} y={y(v) + 4} textAnchor="end" fontSize="11" fill="rgb(var(--ink-2))">{v}</text>
          </g>
        ))}
        {Array.from({ length: n }, (_, i) => {
          const s = by.get(first + i);
          if (!s) return null;
          const h = (H - padT - padB) * (s.waterHa / top);
          return (
            <rect key={i} x={padL + i * bw + 1} y={y(s.waterHa)} width={Math.max(bw - 2, 1)} height={Math.max(h, 0.5)}
              fill={s.source === "LS" ? "rgb(var(--memory))" : "rgb(var(--live))"} opacity={0.9}>
              <title>{`${s.season}: ${ha(s.waterHa)} ${t("common.ha")} (${s.source === "LS" ? "Landsat" : "Sentinel-2"}, ${s.date})${s.rainMm ? `, ${Math.round(s.rainMm)} mm` : ""}`}</title>
            </rect>
          );
        })}
        {series.filter((s) => s.rainMm).map((s) => (
          <circle key={`r${s.season}`} cx={padL + (s.season - first) * bw + bw / 2} cy={ry(s.rainMm as number)} r={2.2}
            fill="rgb(var(--ink-2))" opacity={0.75} />
        ))}
        <line x1={padL} x2={W} y1={y(historicHa)} y2={y(historicHa)} stroke="rgb(var(--built))" strokeWidth={2} />
        <rect x={padL} y={y(historicHa) - 6} width={2} height={12} fill="rgb(var(--built))" />
        {[first, 1995, 2005, 2015, last].map((yr) => (
          <text key={yr} x={padL + (yr - first) * bw + bw / 2} y={H - 6} textAnchor="middle" fontSize="11" fill="rgb(var(--ink-2))">{yr}</text>
        ))}
      </svg>
      <figcaption className="muted mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[13.5px]">
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 bg-memory" />{t("lake.seriesLs")}</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 bg-live" />{t("lake.seriesS2")}</span>
        <span className="inline-flex items-center gap-1.5"><i className="inline-block h-[2px] w-4 bg-built" />{t("lake.seriesHist")} ({ha(historicHa)} {t("common.ha")})</span>
        {rains.length > 0 && <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2 w-2 rounded-full bg-ink-2" />{t("lake.seriesRain")}</span>}
      </figcaption>
    </figure>
  );
}

/** Water memory gauge: a vertical staff gauge (like river level boards) filled to the index. */
export function MemoryGauge({ index, tier }: { index: number | null; tier: string }) {
  const { t } = useT();
  const v = index ?? 0;
  const color = tier === "strong" ? "rgb(var(--built))" : tier === "some" ? "rgb(var(--lost))" : "rgb(var(--memory))";
  return (
    <div className="flex items-stretch gap-4">
      <svg viewBox="0 0 44 160" className="h-40 w-11 shrink-0" aria-hidden="true">
        <rect x="14" y="4" width="16" height="152" fill="rgb(var(--paper-2))" stroke="rgb(var(--line))" />
        {Array.from({ length: 11 }, (_, i) => (
          <line key={i} x1={i % 5 === 0 ? 4 : 9} x2="14" y1={4 + i * 15.2} y2={4 + i * 15.2} stroke="rgb(var(--ink-2))" strokeWidth="1" />
        ))}
        <rect x="14" y={4 + 152 * (1 - v / 100)} width="16" height={152 * (v / 100)} fill={color} opacity="0.9" />
        <line x1="10" x2="36" y1={4 + 152 * (1 - v / 100)} y2={4 + 152 * (1 - v / 100)} stroke={color} strokeWidth="3" />
      </svg>
      <div className="flex flex-col justify-center">
        <div className="display text-[2rem] leading-tight" style={{ color }}>{t(`place.memory.${tier}` as any)}</div>
        {index !== null && <div className="num mt-1 text-[1.25rem] text-ink-2">{t("place.memory.index", { n: index })}</div>}
      </div>
    </div>
  );
}

export function Progress({ steps }: { steps: { label: string; state: "waiting" | "running" | "done" | "skipped" }[] }) {
  return (
    <ol className="space-y-2.5">
      {steps.map((s, i) => (
        <li key={i} className="flex items-center gap-3 text-[15.5px]">
          <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border text-[12px] font-bold ${
            s.state === "done" ? "border-memory bg-memory text-paper" : s.state === "running" ? "border-memory text-memory" : "border-line text-ink-2"}`}>
            {s.state === "running" ? <Loader2 size={13} className="animate-spin" /> : i + 1}
          </span>
          <span className={s.state === "waiting" ? "muted" : ""}>{s.label}</span>
        </li>
      ))}
    </ol>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <div role="alert" className="rounded-lg border border-built/40 bg-built/5 px-4 py-3 text-[15px]">{children}</div>;
}

export function Spinner({ label }: { label?: string }) {
  return <div className="muted flex items-center gap-2 text-[15px]"><Loader2 size={18} className="animate-spin" />{label}</div>;
}

/** Colours baked into the water-memory map layer (handlers/area.py), so the legend always matches the map. */
export const MEMORY_COLORS = { water: "rgb(52 132 238)", lost: "rgb(245 165 36)", built: "rgb(229 72 77)" } as const;

export function MemoryLegend({ dim, wrap }: { dim?: boolean; wrap?: boolean }) {
  const { t } = useT();
  return (
    <div className={`flex gap-1 transition-opacity ${wrap ? "flex-row flex-wrap gap-x-3 sm:flex-col" : "flex-col"} ${dim ? "opacity-40" : ""}`}>
      {([["water", "hero.legendWater"], ["lost", "hero.legendLost"], ["built", "hero.legendBuilt"]] as const).map(([k, label]) => (
        <span key={k} className="flex items-center gap-2"><i className="h-2.5 w-2.5 rounded-sm" style={{ background: MEMORY_COLORS[k] }} />{t(label)}</span>
      ))}
    </div>
  );
}
