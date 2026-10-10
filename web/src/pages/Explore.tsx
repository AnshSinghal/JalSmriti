import * as Tabs from "@radix-ui/react-tabs";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { GradePlate, MemoryLegend, Spinner } from "../components/bits";
import MapView from "../components/MapView";
import { placeUrl } from "../components/SearchBox";
import TimeScrubber from "../components/TimeScrubber";
import { day, ha, pct } from "../lib/format";
import { useT } from "../lib/i18n";
import { useAreaLakes, useAreas, useManifest } from "../lib/queries";
import type { LakeRow } from "../lib/types";

type Sort = "grade" | "lost" | "built" | "size";
const GRADE_ORDER: Record<string, number> = { E: 0, D: 1, C: 2, B: 3, A: 4 };

export default function Explore() {
  const { t, lang } = useT();
  const nav = useNavigate();
  const { areaId = "bengaluru" } = useParams();
  const { data: areas } = useAreas();
  const area = areas?.find((a) => a.id === areaId);
  const { data: man } = useManifest(area);
  const { data: lakes, isLoading } = useAreaLakes(area?.status === "ready" ? areaId : undefined);
  const [sort, setSort] = useState<Sort>("grade");
  const [filter, setFilter] = useState("");
  const [layer, setLayer] = useState<"memory" | "image" | "radar">("memory");
  const [frameIdx, setFrameIdx] = useState(-1);
  const [radarIdx, setRadarIdx] = useState(0);
  const [clicked, setClicked] = useState<[number, number] | null>(null);
  const [hover, setHover] = useState<string | null>(null);

  const rows = useMemo(() => {
    const list = (lakes ?? []).filter((l) => l.kind === "lake" && (!filter || l.name.toLowerCase().includes(filter.toLowerCase())));
    const key = (l: LakeRow) => sort === "grade" ? (GRADE_ORDER[l.grade ?? ""] ?? 9) * 1e6 - l.areaHa
      : sort === "lost" ? -(l.lostHa ?? 0) : sort === "built" ? -(l.builtHa ?? 0) : -l.areaHa;
    return [...list].sort((a, b) => key(a) - key(b));
  }, [lakes, sort, filter]);

  const frames = man?.frames ?? [];
  const fi = frameIdx < 0 ? frames.length - 1 : frameIdx;
  const ev = man?.radarEvents?.[radarIdx];
  const name = area ? area.names[lang] ?? area.names.en : areaId;

  return (
    <div className="grid h-[calc(100vh-4rem)] grid-rows-[55vh_1fr] lg:grid-cols-[400px_minmax(0,1fr)] lg:grid-rows-1 [&>*]:min-w-0">
      <aside className="order-2 flex min-h-0 flex-col border-line lg:order-1 lg:border-r">
        <div className="border-b border-line p-4">
          <label className="label" htmlFor="area-select">{t("explore.area")}</label>
          <select id="area-select" className="field" value={areaId} onChange={(e) => nav(`/explore/${e.target.value}`)}>
            {(areas ?? []).map((a) => <option key={a.id} value={a.id}>{a.names[lang] ?? a.names.en}{a.flood2026 ? ` (${t("areas.flood2026")})` : ""}</option>)}
          </select>
          {area?.story && <p className="muted mt-3 text-[14.5px] leading-snug">{area.story}</p>}
          {area?.stats && (
            <div className="mt-3 grid grid-cols-3 gap-2 text-[13px] text-ink-2">
              <div><div className="num text-[1.35rem] text-memory">{ha(area.stats.historicHa, 0)}</div>{t("common.ha")} {t("areas.historic")}</div>
              <div><div className="num text-[1.35rem] text-lost">{ha(area.stats.lostHa, 0)}</div>{t("common.ha")} {t("areas.lost")}</div>
              <div><div className="num text-[1.35rem] text-built">{ha(area.stats.builtOverHa, 0)}</div>{t("common.ha")} {t("areas.built")}</div>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-2" />
            <input className="field py-2 pl-8 text-[15px]" placeholder={t("explore.filter")} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={t("explore.filter")} />
          </div>
          <select className="field w-auto py-2 text-[15px]" value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label={t("explore.sort")}>
            <option value="grade">{t("sort.grade")}</option>
            <option value="lost">{t("sort.lost")}</option>
            <option value="built">{t("sort.built")}</option>
            <option value="size">{t("sort.size")}</option>
          </select>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {area && area.status !== "ready" && (
            <p className="muted p-4 text-[15px]">{t("explore.notReady", { name, stage: area.stage ?? "waiting" })}</p>
          )}
          {isLoading && <div className="p-4"><Spinner label={t("common.loading")} /></div>}
          {lakes && (
            <>
              <p className="muted px-4 pt-3 text-[13.5px]">{rows.length === 1 ? t("areas.lake1") : t("explore.count", { n: rows.length })}</p>
              <ul className="divide-y divide-line">
                {rows.map((l) => (
                  <li key={l.lakeId}>
                    <Link to={`/lake/${l.lakeId}`} onMouseEnter={() => setHover(l.lakeId)} onMouseLeave={() => setHover(null)}
                      className="flex items-center gap-3 px-4 py-3 hover:bg-paper-2">
                      <GradePlate grade={l.grade} size="sm" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[15.5px] font-semibold">{l.name}</div>
                        <div className="muted text-[13px]">
                          {ha(l.areaHa)} {t("common.ha")}{l.lostPct ? `, ${pct(l.lostPct)} ${t("areas.lost")}` : ""}{l.builtHa ? `, ${ha(l.builtHa)} ${t("common.ha")} ${t("areas.built")}` : ""}
                        </div>
                      </div>
                    </Link>
                  </li>
                ))}
                {rows.length === 0 && <li className="muted p-4 text-[15px]">{t("explore.empty")}</li>}
              </ul>
            </>
          )}
        </div>
      </aside>

      <section className="relative order-1 min-h-0 lg:order-2">
        {area && (
          <MapView key={area.id} className="absolute inset-0" bbox={area.bbox}
            memory={layer === "memory" && man?.layers.memory ? { url: man.layers.memory.url, corners: man.layers.memory.corners, opacity: 0.9 } : null}
            frame={layer === "image" && frames[fi] ? { url: frames[fi].url, corners: frames[fi].corners } : null}
            radar={layer === "radar" && ev ? { url: ev.url, corners: ev.corners, opacity: 0.95 } : null}
            lakesUrl={man?.lakesUrl ?? null} highlightLake={hover}
            onLakeClick={(p) => nav(`/lake/${p.lakeId}`)}
            onMapClick={(ll) => setClicked(ll)} marker={clicked} />
        )}
        <div className="absolute left-3 top-3 z-10 max-w-[calc(100%-5rem)]">
          <Tabs.Root value={layer} onValueChange={(v) => setLayer(v as any)}>
            <Tabs.List aria-label={t("explore.layers")} className="flex flex-wrap gap-1 rounded-lg border border-line bg-paper/95 p-1 shadow-sm backdrop-blur">
              <Tabs.Trigger value="memory" className="rounded-md px-3 py-1.5 text-[14px] font-semibold text-ink-2 data-[state=active]:bg-ink data-[state=active]:text-paper">{t("layer.memory")}</Tabs.Trigger>
              <Tabs.Trigger value="image" disabled={!frames.length} className="rounded-md px-3 py-1.5 text-[14px] font-semibold text-ink-2 disabled:opacity-40 data-[state=active]:bg-ink data-[state=active]:text-paper">{t("layer.image")}</Tabs.Trigger>
              {(man?.radarEvents?.length ?? 0) > 0 && (
                <Tabs.Trigger value="radar" className="rounded-md px-3 py-1.5 text-[14px] font-semibold text-ink-2 data-[state=active]:bg-ink data-[state=active]:text-paper">{t("layer.radar")}</Tabs.Trigger>
              )}
            </Tabs.List>
          </Tabs.Root>
        </div>
        {layer === "image" && frames.length > 0 && (
          <div className="absolute inset-x-3 bottom-8 z-10 rounded-lg border border-line bg-paper/95 px-4 py-3 shadow-lg backdrop-blur sm:right-auto sm:w-[min(640px,calc(100%-1.5rem))]">
            <TimeScrubber labels={frames.map((f) => (f.season === "latest" ? day(f.date, lang) : String(f.season)))} index={fi} onChange={setFrameIdx}
              sublabel={frames[fi] ? `${frames[fi].source === "LS" ? "Landsat" : "Sentinel-2"}, ${day(frames[fi].date, lang)}` : undefined} compact />
          </div>
        )}
        {layer === "radar" && ev && (
          <div className="absolute inset-x-3 bottom-8 z-10 max-w-xl rounded-lg border border-line bg-paper/95 p-4 shadow-lg backdrop-blur">
            {man!.radarEvents.length > 1 && (
              <select className="field mb-2 py-1.5 text-[14.5px]" value={radarIdx} onChange={(e) => setRadarIdx(Number(e.target.value))}>
                {man!.radarEvents.map((r, i) => <option key={r.date} value={i}>{r.title}</option>)}
              </select>
            )}
            <div className="font-semibold">{ev.title}</div>
            <p className="mt-1 text-[14.5px] text-ink-2">{ev.detail}</p>
            {ev.unusualHa >= 5
              ? <p className="mt-2 text-[14px]"><span className="mr-2 inline-block h-2.5 w-2.5 rounded-sm bg-built" />{t("explore.radarCaption", { date: day(ev.sceneDate, lang), ha: ha(ev.unusualHa, 0) })}</p>
              : <p className="mt-2 text-[14px] text-ink-2">{t("explore.radarLittle", { date: day(ev.sceneDate, lang) })}</p>}
          </div>
        )}
        {clicked && (
          <div className="absolute right-3 top-14 z-10 w-[min(320px,calc(100%-1.5rem))] rounded-lg border border-line bg-paper p-4 shadow-xl">
            <div className="num text-[1.05rem]">{clicked[1].toFixed(4)} N, {clicked[0].toFixed(4)} E</div>
            <div className="mt-3 flex flex-col gap-2">
              <Link className="btn-primary" to={placeUrl({ lat: clicked[1], lon: clicked[0] })}>{t("explore.checkHere")}</Link>
              <Link className="btn-quiet" to={`/lake/find?lat=${clicked[1].toFixed(5)}&lon=${clicked[0].toFixed(5)}`}>{t("explore.analyseHere")}</Link>
              <button className="btn-ghost" onClick={() => setClicked(null)}>{t("common.close")}</button>
            </div>
          </div>
        )}
        {layer === "memory" && man?.layers.memory && (
          <div className="pointer-events-none absolute bottom-8 left-3 z-10 rounded-md bg-paper/95 px-3 py-2.5 text-[13px] shadow-sm backdrop-blur"><MemoryLegend /></div>
        )}
        {!clicked && layer === "memory" && (
          <p className="pointer-events-none absolute left-3 top-[3.9rem] z-0 hidden max-w-[22rem] rounded-md bg-paper/90 px-2.5 py-1.5 text-[13px] leading-snug text-ink-2 shadow-sm lg:block">{t("explore.hint")}</p>
        )}
      </section>
    </div>
  );
}
