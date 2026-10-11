import { motion } from "framer-motion";
import { BadgeCheck, Droplets, EyeOff, FileSignature, Home, KeyRound, Link2, Scale, ShieldCheck, Waves } from "lucide-react";
import { lazy, Suspense, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { FindingList, GradePlate, MemoryLegend, Stat } from "../components/bits";
import SearchBox from "../components/SearchBox";
import Timelapse, { useLakeFrames } from "../components/Timelapse";
import TimeScrubber from "../components/TimeScrubber";
import { day, ha, pct } from "../lib/format";
import { useT } from "../lib/i18n";
import { usePersona, type Persona } from "../lib/persona";
import { useAreaLakes, useAreas, useLake, useManifest } from "../lib/queries";
import type { Area } from "../lib/types";
import { CASES, CASE_SUMMARY } from "../data/cases";

const MapView = lazy(() => import("../components/MapView"));

function HeroMap() {
  const { t, lang } = useT();
  const { data: areas } = useAreas();
  const blr = areas?.find((a) => a.id === "bengaluru");
  const { data: man } = useManifest(blr);
  const frames = man?.frames ?? [];
  const [idx, setIdx] = useState<number>(-1);
  const [showMemory, setShowMemory] = useState(true);
  // open on the last post-monsoon season (chosen for clear skies); the newest look may still be cloudy
  const lastSeason = frames.map((f) => f.season).lastIndexOf(frames.filter((f) => f.season !== "latest").slice(-1)[0]?.season as any);
  const i = idx < 0 ? (lastSeason >= 0 ? lastSeason : frames.length - 1) : idx;
  const frame = frames[i];
  const labels = frames.map((f) => (f.season === "latest" ? day(f.date, lang) : String(f.season)));
  const ready = !!man && frames.length > 0;
  return (
    <div className="relative flex h-full min-h-[440px] flex-col overflow-hidden rounded-xl border border-line bg-paper-2">
      <div className="relative flex-1">
        {ready ? (
          <Suspense fallback={<div className="skeleton absolute inset-0" />}>
            <MapView className="absolute inset-0" bbox={man!.bbox} scrollZoom={false} revealMs={1800}
              memory={showMemory && man!.layers.memory ? { url: man!.layers.memory.url, corners: man!.layers.memory.corners, opacity: 0.92 } : null}
              frame={frame ? { url: frame.url, corners: frame.corners, opacity: 1, dim: showMemory } : null}
              attribution="Landsat (USGS), Sentinel-2 (Copernicus), JRC Global Surface Water" />
          </Suspense>
        ) : (
          <div className="absolute inset-0 grid place-items-center p-8 text-center">
            <p className="muted max-w-sm">{blr?.status === "ready" || !blr ? t("common.loading") : t("hero.loadingArea")}</p>
          </div>
        )}
        <div className="absolute left-3 top-3 max-w-[calc(100%-4.5rem)] rounded-md bg-paper/95 px-3 py-2.5 text-[12.5px] shadow-sm backdrop-blur sm:text-[13px]">
          <label className="tap flex cursor-pointer items-center gap-2 font-semibold">
            <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--memory))]" checked={showMemory} onChange={(e) => setShowMemory(e.target.checked)} disabled={!ready} />
            {t("layer.memory")}
          </label>
          <div className="mt-1.5 sm:pl-6"><MemoryLegend dim={!showMemory} wrap /></div>
        </div>
      </div>
      {ready && (
        <div className="border-t border-line bg-paper px-4 py-3">
          <TimeScrubber labels={labels} index={i} onChange={setIdx}
            sublabel={frame ? `${frame.source === "LS" ? "Landsat" : "Sentinel-2"}, ${day(frame.date, lang)}` : undefined} />
        </div>
      )}
    </div>
  );
}

function Specimen() {
  const { t, lang } = useT();
  const { data: lakes } = useAreaLakes("bengaluru");
  const pick = useMemo(() => {
    if (!lakes?.length) return undefined;
    return lakes.find((l) => /bellandur/i.test(l.name)) ?? [...lakes].filter((l) => l.grade && "DE".includes(l.grade)).sort((a, b) => b.areaHa - a.areaHa)[0];
  }, [lakes]);
  const { data: lake } = useLake(pick?.lakeId);
  const frames = useLakeFrames(lake?.lakeId, lake?.frames, lake?.latestDate, lake?.frameUrls);
  if (!lake) return null;
  const m = lake.metrics;
  return (
    <section className="mx-auto mt-24 max-w-[1400px] px-4 sm:px-6">
      <div className="grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:items-start [&>*]:min-w-0">
        <div>
          <h2>{t("specimen.title")}</h2>
          <p className="mt-4 max-w-prose text-[17.5px]">{t("specimen.body")}</p>
          <div className="mt-8 flex items-center gap-4">
            <GradePlate grade={m.grade.grade} size="lg" />
            <div>
              <Link to={`/lake/${lake.lakeId}`} className="display tap inline-flex items-center text-[1.9rem] leading-tight hover:text-memory">{lake.name}</Link>
              <div className="muted text-[15px]">{lake.area ? lake.area.names[lang] ?? lake.area.names.en : ""}, {t(`grade.${m.grade.grade ?? "none"}` as any)}</div>
            </div>
          </div>
          <div className="mt-6 grid grid-cols-3 gap-5">
            <Stat label={t("lake.historic")} value={ha(m.historicHa)} unit={t("common.ha")} tone="memory" />
            <Stat label={t("lake.lost")} value={pct(m.lostPct)} tone="lost" />
            <Stat label={t("lake.weeds")} value={m.quality?.weedPct != null ? pct(m.quality.weedPct) : "-"} tone="built" />
          </div>
          <div className="mt-6"><FindingList findings={lake.findings.slice(0, 3)} /></div>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link to={`/lake/${lake.lakeId}`} className="btn-primary">{lake.name}</Link>
            <Link to="/place" className="btn-quiet">{t("specimen.cta")}</Link>
          </div>
        </div>
        <Timelapse frames={frames} caption={t("specimen.caption", { name: lake.name })} />
      </div>
    </section>
  );
}

function AreaRow({ a }: { a: Area }) {
  const { t, lang } = useT();
  const s = a.stats;
  const name = a.names[lang] ?? a.names.en;
  const total = Math.max(s?.historicHa ?? 0, 1);
  return (
    <Link to={`/explore/${a.id}`} className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-6 gap-y-2 py-4 sm:grid-cols-[14rem_minmax(0,1fr)_auto]"
      aria-label={t("areas.open", { name })}>
      <div>
        <div className="display text-[1.55rem] leading-tight group-hover:text-memory">{name}</div>
        <div className="muted text-[14px]">
          {a.state}
          {a.flood2026 && <span className="tag ml-2 bg-built/10 text-built">{t("areas.flood2026")}</span>}
        </div>
      </div>
      {s ? (
        <div className="col-span-2 sm:col-span-1">
          <div className="relative h-3 w-full overflow-hidden rounded-sm bg-memory/80" title={`${ha(s.historicHa)} ${t("common.ha")}`}>
            <div className="absolute inset-y-0 right-0 bg-lost" style={{ width: `${(100 * s.lostHa) / total}%` }} />
            <div className="absolute inset-y-0 right-0 bg-built" style={{ width: `${(100 * s.builtOverHa) / total}%` }} />
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-4 text-[13.5px] text-ink-2">
            <span><b className="num text-[15px] text-memory">{ha(s.historicHa, 0)}</b> {t("common.ha")} {t("areas.historic")}</span>
            <span><b className="num text-[15px] text-lost">{ha(s.lostHa, 0)}</b> {t("common.ha")} {t("areas.lost")}</span>
            <span><b className="num text-[15px] text-built">{ha(s.builtOverHa, 0)}</b> {t("common.ha")} {t("areas.built")}</span>
          </div>
        </div>
      ) : (
        <div className="muted col-span-2 text-[14.5px] sm:col-span-1">{t("areas.pending")}</div>
      )}
      <div className="num hidden text-right text-[1.2rem] text-ink-2 sm:block">{s ? (s.lakes === 1 ? t("areas.lake1") : t("areas.lakes", { n: s.lakes })) : ""}</div>
    </Link>
  );
}

const STEPS = ["s1", "s2", "s3", "s4", "s5"] as const;

function PathTile({ icon, title, body, active, onClick, to }: {
  icon: ReactNode; title: string; body: string; active?: boolean; onClick?: () => void; to?: string;
}) {
  const cls = `group flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left transition-colors ${
    active ? "border-memory bg-memory/5" : "border-line bg-paper hover:border-ink-2"}`;
  const inner = (
    <>
      <span className={`mt-0.5 shrink-0 ${active ? "text-memory" : "text-ink-2 group-hover:text-memory"}`} aria-hidden="true">{icon}</span>
      <span className="min-w-0">
        <span className="block text-[16px] font-semibold leading-snug">{title}</span>
        <span className="muted block text-[14px] leading-snug">{body}</span>
      </span>
    </>
  );
  return to ? <Link to={to} className={cls}>{inner}</Link> : <button type="button" onClick={onClick} aria-pressed={active} className={cls}>{inner}</button>;
}

/** "What brings you here?": four doors into the site for someone who has never seen it. Renting/buying and living
 *  here both start with a place check; the choice decides which steps the place page shows first. */
function PathChooser({ onPlace, chosen }: { onPlace: (p: Persona) => void; chosen: Persona | null }) {
  const { t } = useT();
  return (
    <div className="mt-8 max-w-xl">
      <h2 className="text-[1.25rem] font-semibold [font-stretch:100%]">{t("path.title")}</h2>
      <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
        <PathTile icon={<KeyRound size={20} />} title={t("path.home.t")} body={t("path.home.b")} active={chosen === "home"} onClick={() => onPlace("home")} />
        <PathTile icon={<Home size={20} />} title={t("path.resident.t")} body={t("path.resident.b")} active={chosen === "resident"} onClick={() => onPlace("resident")} />
        <PathTile icon={<Waves size={20} />} title={t("path.lake.t")} body={t("path.lake.b")} to="/defend" />
        <PathTile icon={<Droplets size={20} />} title={t("path.water.t")} body={t("path.water.b")} to="/waterlogging" />
      </div>
      <Link to="/console" className="link mt-3 inline-flex items-center gap-1.5 text-[14px] text-ink-2"><ShieldCheck size={15} aria-hidden="true" />{t("path.official")}</Link>
    </div>
  );
}

const TEASER = ["velachery", "kendriyavihar", "payakapuram", "nakkhu"];
const VERDICT_TONE: Record<string, string> = { avoid: "text-built", think: "text-[#9a6206] dark:text-lost", checks: "text-memory", fine: "text-live" };

/** Sixteen places that flooded, and what JalSmriti reads for them: a door to the Past floods page. */
function ProofTeaser() {
  const { t } = useT();
  const g = CASE_SUMMARY.groundRenter as Record<string, number>;
  const rows = TEASER.map((id) => CASES.find((c) => c.id === id)).filter(Boolean) as typeof CASES;
  return (
    <section className="mx-auto mt-24 max-w-[1400px] px-4 sm:px-6">
      <div className="grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] [&>*]:min-w-0">
        <div>
          <h2>{t("proofTeaser.title")}</h2>
          <p className="mt-4 max-w-prose text-[17.5px] text-ink-2">{t("proofTeaser.lede", { n: CASES.length, warned: (g.avoid ?? 0) + (g.think ?? 0) })}</p>
          <Link to="/proof" className="btn-primary mt-6">{t("proofTeaser.cta", { n: CASES.length })}</Link>
        </div>
        <ul className="divide-y divide-line border-y border-line">
          {rows.map((c) => (
            <li key={c.id}>
              <Link to={`/proof#${c.id}`} className="grid gap-1 py-4 hover:text-memory sm:grid-cols-[minmax(0,1fr)_auto] sm:items-baseline sm:gap-6">
                <span className="min-w-0"><span className="block font-semibold">{c.label}</span><span className="muted text-[14px]">{c.when}</span></span>
                <span className="text-[14.5px] sm:text-right">
                  <span className="text-ink-2">{t(`place.memory.${c.tier}` as any)}, {c.index}</span>
                  <span className={`ml-2 font-semibold ${VERDICT_TONE[c.verdict.ground]}`}>{t(`verdict.level.${c.verdict.ground}` as any)}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export default function Landing() {
  const { t } = useT();
  const { data: areas } = useAreas();
  const [, setPersona] = usePersona();
  const [chosen, setChosen] = useState<Persona | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  function choose(p: Persona) {
    setPersona(p);
    setChosen(p);
    searchRef.current?.focus();
    searchRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  return (
    <div>
      <section className="mx-auto grid max-w-[1400px] gap-8 px-4 pt-8 sm:px-6 lg:min-h-[calc(100vh-4rem)] lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:items-stretch lg:pb-8 [&>*]:min-w-0">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: [0.2, 0.7, 0.1, 1] }}
          className="flex flex-col justify-center py-4 lg:py-10">
          <h1 className="max-w-[12ch]">{t("hero.title")}</h1>
          <p className="mt-6 max-w-[46ch] text-[1.15rem] leading-relaxed text-ink-2">{t("hero.lede")}</p>
          <div className="mt-8 max-w-xl">
            <SearchBox large inputRef={searchRef}
              placeholder={chosen === "home" ? t("path.focusHome") : chosen === "resident" ? t("path.focusResident") : undefined} />
          </div>
          <PathChooser onPlace={choose} chosen={chosen} />
        </motion.div>
        <div className="h-[62vh] min-h-[460px] lg:h-auto">
          <HeroMap />
          <p className="muted mt-2 text-[13.5px]">{t("hero.mapCaption")}</p>
        </div>
      </section>

      <Specimen />

      <ProofTeaser />

      <section className="mx-auto mt-24 max-w-[1400px] px-4 sm:px-6">
        <div className="max-w-prose">
          <h2>{t("areas.title")}</h2>
          <p className="mt-4 text-[17.5px] text-ink-2">{t("areas.lede")}</p>
        </div>
        <div className="mt-8 divide-y divide-line border-y border-line">
          {(areas ?? []).map((a) => <AreaRow key={a.id} a={a} />)}
          {!areas && Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton my-4 h-12" />)}
        </div>
      </section>

      <section className="mx-auto mt-24 max-w-[1400px] px-4 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] [&>*]:min-w-0">
          <div>
            <h2>{t("defend.title")}</h2>
            <p className="mt-4 max-w-prose text-[17.5px] text-ink-2">{t("defend.lede")}</p>
            <Link to="/defend" className="btn-memory mt-6">{t("nav.defend")}</Link>
          </div>
          <ol className="relative border-l-2 border-line pl-8">
            {STEPS.map((s, i) => (
              <li key={s} className="relative pb-7 last:pb-0">
                <span className="num absolute -left-[3.05rem] top-0 grid h-9 w-9 place-items-center rounded-full border-2 border-line bg-paper text-[1.1rem] text-ink">{i + 1}</span>
                <h3>{t(`defend.${s}.t` as any)}</h3>
                <p className="mt-1.5 max-w-prose text-[16px] text-ink-2">{t(`defend.${s}.b` as any)}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="mx-auto mt-24 max-w-[1400px] px-4 sm:px-6">
        <h2 className="max-w-prose">{t("trust.title")}</h2>
        <dl className="mt-8 grid gap-x-10 gap-y-7 md:grid-cols-2 xl:grid-cols-3">
          {([["sig", FileSignature], ["ledger", Link2], ["rules", Scale], ["privacy", EyeOff], ["honest", BadgeCheck]] as const).map(([k, Icon]) => (
            <div key={k} className="flex gap-4">
              <Icon size={22} className="mt-1 shrink-0 text-memory" aria-hidden="true" />
              <div>
                <dt className="text-[1.1rem] font-semibold">{t(`trust.${k}.t` as any)}</dt>
                <dd className="mt-1 text-[15.5px] text-ink-2">{t(`trust.${k}.b` as any)}</dd>
              </div>
            </div>
          ))}
        </dl>
      </section>

      <section className="mx-auto mt-24 max-w-[1400px] px-4 sm:px-6">
        <div className="grid gap-8 rounded-xl bg-ink px-6 py-10 text-paper sm:px-10 lg:grid-cols-[minmax(0,4fr)_minmax(0,8fr)] [&>*]:min-w-0">
          <h2 className="text-paper">{t("built.title")}</h2>
          <div className="space-y-4 text-[16.5px] leading-relaxed text-paper/85">
            <p>{t("built.data")}</p>
            <p>{t("built.aws")}</p>
          </div>
        </div>
      </section>
    </div>
  );
}
