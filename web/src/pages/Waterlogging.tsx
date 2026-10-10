import { Camera, History, ShieldCheck } from "lucide-react";
import type { Map as MLMap } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorNote } from "../components/bits";
import MapView, { type MapPoint } from "../components/MapView";
import ShareButtons from "../components/ShareButtons";
import WaterReportDialog, { DEPTHS, DEPTH_BG, DepthIcon, DepthTag, StatusTag, agoText, depthColor, isDepth } from "../components/WaterReportDialog";
import { useAuth } from "../lib/auth";
import { dateTime, day } from "../lib/format";
import { useT } from "../lib/i18n";
import { useWaterReports } from "../lib/queries";
import { useThemeValue } from "../lib/theme";
import type { WaterReport } from "../lib/types";

type Window = 48 | 168;
type LatLon = { lat: number; lon: number };

/** India and Nepal, the map's view when nobody has reported anything in the window. */
const INDIA: [number, number, number, number] = [68.1, 6.5, 97.4, 35.7];
const FIT_PADDING = { top: 56, right: 56, bottom: 76, left: 56 };

function boundsOf(rs: WaterReport[]): [number, number, number, number] | null {
  if (!rs.length) return null;
  let w = 180, s = 90, e = -180, n = -90;
  for (const r of rs) {
    w = Math.min(w, r.lon); e = Math.max(e, r.lon);
    s = Math.min(s, r.lat); n = Math.max(n, r.lat);
  }
  return [w, s, e, n];
}

const smooth = (): ScrollBehavior => (window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");

/** Re-render now and then so "12 min ago" stays true while the page is open. */
function useNow(ms: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

function parseStart(sp: URLSearchParams): LatLon | null {
  const lat = Number(sp.get("lat")), lon = Number(sp.get("lon"));
  if (!sp.get("lat") || !sp.get("lon") || !Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}

function ReportItem({ r, selected, now, onSelect }: { r: WaterReport; selected: boolean; now: number; onSelect: () => void }) {
  const { t, lang } = useT();
  const summary = r.ai?.summary || null;
  const thumb = "block h-[72px] w-24 shrink-0 overflow-hidden rounded-md bg-paper-3 sm:h-[90px] sm:w-[120px]";
  const img = r.thumbUrl ? <img src={r.thumbUrl} alt={summary ?? ""} className="h-full w-full object-cover" loading="lazy" /> : null;
  return (
    <li id={`wl-${r.reportId}`} className="scroll-mt-20">
      <div className={`relative flex gap-3 px-4 py-3.5 transition-colors sm:gap-4 sm:px-6 ${selected ? "bg-paper-2" : "hover:bg-paper-2/60"}`}>
        {selected && <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-memory" />}
        {r.url
          ? <a href={r.url} target="_blank" rel="noreferrer" className={thumb} aria-label={t("wl.openPhoto")} onClick={onSelect}>{img}</a>
          : <div className={thumb}>{img}</div>}
        <button type="button" onClick={onSelect} aria-pressed={selected} className="min-w-0 flex-1 rounded-sm text-left">
          <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
            <DepthTag depth={r.depth} />
            <StatusTag status={r.status} />
            <time dateTime={r.seenAt} title={dateTime(r.seenAt, lang)} className="ml-0.5 text-[13px] text-ink-2">{agoText(r.seenAt, t, now)}</time>
          </span>
          {summary && (
            <span className="mt-1.5 block text-[14.5px] leading-snug text-ink-2"><span className="font-semibold text-ink">{t("wl.ai")}:</span> {summary}</span>
          )}
          {r.note && <span className="mt-1 block text-[14.5px] leading-snug">“{r.note}”</span>}
          {r.oldPhoto && r.capturedAt && (
            <span className="mt-1 flex items-center gap-1.5 text-[13px] text-ink-2"><History size={14} className="shrink-0 text-lost" aria-hidden="true" />{t("wl.oldPhoto", { date: day(r.capturedAt, lang) })}</span>
          )}
          {r.status === "verified" && r.review?.note && (
            <span className="mt-1 flex items-start gap-1.5 text-[13.5px] leading-snug text-ink-2"><ShieldCheck size={14} className="mt-0.5 shrink-0 text-live" aria-hidden="true" />{r.review.by}: {r.review.note}</span>
          )}
          <span className="mt-1 block text-[13px] text-ink-2">{t("wl.by", { who: r.uploader ?? "-" })}</span>
        </button>
      </div>
    </li>
  );
}

export default function Waterlogging() {
  const { t } = useT();
  const { user, ready, openAuth, dialog: authDialog } = useAuth();
  const theme = useThemeValue();
  const [sp, setSp] = useSearchParams();
  const [hours, setHours] = useState<Window>(48);
  const { data: reports, isLoading, error, refetch } = useWaterReports(hours);
  const [selected, setSelected] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState<LatLon | null>(null);
  const [pending, setPending] = useState(false);       // asked to report while signed out: carry on after sign-in
  const [mapReady, setMapReady] = useState(false);
  const mapRef = useRef<MLMap | null>(null);
  const mapBox = useRef<HTMLElement>(null);
  const fitted = useRef<Window | null>(null);           // the window the map was last fitted to
  const now = useNow(60_000);

  const shown = useMemo(() => (reports ?? []).filter((r) => Number.isFinite(r.lat) && Number.isFinite(r.lon)), [reports]);
  // depth colours are read from the theme tokens, so they are worked out again when the theme changes
  const points = useMemo<MapPoint[] | null>(
    () => (reports ? shown.map((r) => ({ id: r.reportId, lon: r.lon, lat: r.lat, color: depthColor(r.depth), selected: r.reportId === selected })) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [reports, shown, selected, theme],
  );
  const noDepth = shown.some((r) => !isDepth(r.depth));

  function report(s: LatLon | null = null) {
    setStart(s);
    if (user) setOpen(true);
    else { setPending(true); openAuth("signin", t("auth.needed")); }
  }

  // ?report=1&lat=..&lon=.. (from a place's page): open the dialog there, once we know whether someone is signed in
  useEffect(() => {
    if (!ready || sp.get("report") !== "1") return;
    const s = parseStart(sp);
    setSp({}, { replace: true });                        // a refresh or the back button should not open it again
    report(s);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, sp]);

  useEffect(() => {
    if (!pending || authDialog) return;                  // wait while the sign-in dialog is open
    setPending(false);
    if (user) setOpen(true);                             // signed in: on to the report; closed without: drop it
  }, [pending, user, authDialog]);

  // fit the map to the reports when a window's data first arrives (not on every minute's refresh)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !reports || fitted.current === hours) return;
    const first = fitted.current === null;
    fitted.current = hours;
    const b = boundsOf(shown);
    if (!b && first) return;                             // already showing India
    map.fitBounds(b ?? INDIA, { padding: FIT_PADDING, maxZoom: 13, duration: 800 });
  }, [mapReady, reports, shown, hours]);

  /** On phones the map sits above the list: bring it back when its middle is off screen. */
  function revealMap() {
    const el = mapBox.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const mid = r.top + r.height / 2;
    if (mid < 64 || mid > window.innerHeight) el.scrollIntoView({ block: "start", behavior: smooth() });
  }

  function flyTo(r: WaterReport, minZoom: number) {
    const map = mapRef.current;
    if (map && Number.isFinite(r.lat) && Number.isFinite(r.lon)) map.flyTo({ center: [r.lon, r.lat], zoom: Math.max(map.getZoom(), minZoom), duration: 900 });
  }

  function selectFromList(r: WaterReport) {
    setSelected(r.reportId);
    flyTo(r, 14);
    revealMap();
  }

  function selectFromMap(id: string) {
    setSelected(id);
    requestAnimationFrame(() => document.getElementById(`wl-${id}`)?.scrollIntoView({ block: "nearest", behavior: smooth() }));
  }

  function seeOnMap(r: WaterReport) {
    setOpen(false);
    setSelected(r.reportId);
    if (hours === 48 && r.seenAt && Date.now() - Date.parse(r.seenAt) > 48 * 3600_000) {
      fitted.current = 168;                              // an older photo: widen the window, keep the view on it
      setHours(168);
    }
    flyTo(r, 15);
    setTimeout(revealMap, 80);                           // after the dialog has let go of the page's scroll
  }

  const n = shown.length;
  return (
    <div className="grid lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] [&>*]:min-w-0">
      <div className="order-2 border-line lg:order-1 lg:min-h-[calc(100vh-4rem)] lg:border-r">
        <div className="px-4 pb-5 pt-6 sm:px-6 lg:pt-9">
          <h1 className="text-[clamp(2.3rem,4.4vw,3.5rem)]">{t("wl.title")}</h1>
          <p className="mt-3 max-w-prose text-[16.5px] leading-relaxed text-ink-2">{t("wl.lede")}</p>
          <div className="mt-5 flex flex-wrap gap-2">
            <button type="button" className="btn-primary w-full sm:w-auto" onClick={() => report()}>
              <Camera size={17} aria-hidden="true" />{t("wl.report")}
            </button>
            <ShareButtons text={t("share.water")} path="/waterlogging" />
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-y border-line px-4 py-2.5 sm:px-6">
          <div role="group" className="inline-flex rounded-lg border border-line p-1">
            {([48, 168] as const).map((h) => (
              <button key={h} type="button" aria-pressed={hours === h} onClick={() => setHours(h)}
                className={`rounded-md px-3 py-1.5 text-[14px] font-semibold transition-colors ${hours === h ? "bg-ink text-paper" : "text-ink-2 hover:text-ink"}`}>
                {t(h === 48 ? "wl.window.48" : "wl.window.168")}
              </button>
            ))}
          </div>
          <p className="text-[14px] text-ink-2" aria-live="polite">{reports ? (n === 1 ? t("wl.count1") : t("wl.count", { n })) : ""}</p>
        </div>

        {isLoading ? (
          <>
            <p className="sr-only" role="status">{t("common.loading")}</p>
            <ul aria-hidden="true" className="divide-y divide-line">
              {[0, 1, 2, 3].map((i) => (
                <li key={i} className="flex gap-3 px-4 py-3.5 sm:gap-4 sm:px-6">
                  <div className="skeleton h-[72px] w-24 shrink-0 sm:h-[90px] sm:w-[120px]" />
                  <div className="flex-1 space-y-2.5 pt-1"><div className="skeleton h-4 w-44" /><div className="skeleton h-3.5 w-full max-w-[24rem]" /><div className="skeleton h-3.5 w-32" /></div>
                </li>
              ))}
            </ul>
          </>
        ) : error ? (
          <div className="px-4 py-6 sm:px-6">
            <ErrorNote>{t("common.error", { msg: (error as Error).message })}</ErrorNote>
            <button type="button" className="btn-quiet mt-3" onClick={() => refetch()}>{t("common.retry")}</button>
          </div>
        ) : n === 0 ? (
          <div className="flex flex-col items-start px-4 py-10 sm:px-6">
            <DepthIcon depth="ankle" className="h-14 w-14 text-memory/70" />
            <p className="mt-3 max-w-prose text-[16px] leading-relaxed text-ink-2">{t("wl.empty")}</p>
            <button type="button" className="btn-primary mt-5" onClick={() => report()}><Camera size={17} aria-hidden="true" />{t("wl.report")}</button>
          </div>
        ) : (
          <ul className="divide-y divide-line border-b border-line">
            {shown.map((r) => <ReportItem key={r.reportId} r={r} now={now} selected={r.reportId === selected} onSelect={() => selectFromList(r)} />)}
          </ul>
        )}
      </div>

      <section ref={mapBox} className="relative order-1 h-[55vh] min-h-[300px] scroll-mt-16 border-b border-line lg:sticky lg:top-16 lg:order-2 lg:h-[calc(100vh-4rem)] lg:self-start lg:border-b-0">
        <MapView className="absolute inset-0" bbox={INDIA} attribution="" points={points}
          onPointClick={selectFromMap} onMapClick={() => setSelected(null)}
          onReady={(m) => { mapRef.current = m; setMapReady(true); }} />
        {n > 0 && (
          <p className="pointer-events-none absolute left-3 top-3 z-10 max-w-[calc(100%-4.5rem)] rounded-md bg-paper/90 px-2.5 py-1.5 text-[13px] leading-snug text-ink-2 shadow-sm">{t("wl.mapHint")}</p>
        )}
        <div className="pointer-events-none absolute bottom-8 left-3 z-10 rounded-md bg-paper/95 px-3 py-2 text-[13px] shadow-sm backdrop-blur">
          <ul className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-1">
            {[...DEPTHS, ...(noDepth ? (["none"] as const) : [])].map((d) => (
              <li key={d} className="flex items-center gap-2 whitespace-nowrap">
                <i aria-hidden="true" className={`h-3.5 w-3.5 shrink-0 rounded-full border-2 border-white ${DEPTH_BG[d]}`} />{t(`wl.depth.${d}` as any)}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <WaterReportDialog open={open} onClose={() => setOpen(false)} start={start} onSee={seeOnMap} />
    </div>
  );
}
