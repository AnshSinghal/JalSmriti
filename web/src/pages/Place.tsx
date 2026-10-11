import { useQueryClient } from "@tanstack/react-query";
import { BellRing, Camera, Check, Crosshair, FileSignature, RotateCcw, Waves } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ErrorNote, FindingList, MemoryGauge, Progress } from "../components/bits";
import ListenButton from "../components/ListenButton";
import MapView from "../components/MapView";
import HeatPanel from "../components/place/HeatPanel";
import PeopleReports from "../components/place/PeopleReports";
import RainStrip from "../components/place/RainStrip";
import { ReportButton, ReportStatus, usePlaceReport } from "../components/place/report";
import ThisWeek from "../components/place/ThisWeek";
import VerdictCard, { useAnswers } from "../components/place/VerdictCard";
import SearchBox, { placeUrl } from "../components/SearchBox";
import ShareButtons from "../components/ShareButtons";
import Timelapse from "../components/Timelapse";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { day, ha } from "../lib/format";
import { geohash } from "../lib/geohash";
import { useT } from "../lib/i18n";
import { usePersona } from "../lib/persona";
import { useActivity, useAreas, useJob, useManifest } from "../lib/queries";
import type { Action, Finding, PlaceResult } from "../lib/types";
import { metricsFindingsPlace } from "./placeFindings";

function Picker({ mode, start }: { mode: "place" | "lake"; start?: [number, number] }) {
  const { t } = useT();
  const nav = useNavigate();
  const [center, setCenter] = useState<[number, number]>(start ?? [77.6, 12.97]);
  const mapRef = useRef<any>(null);
  const goTo = (lat: number, lon: number) =>
    nav(mode === "lake" ? `/lake/find?lat=${lat.toFixed(5)}&lon=${lon.toFixed(5)}` : placeUrl({ lat, lon }));
  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6">
      <h1 className="max-w-[16ch]">{mode === "lake" ? t("defend.pointMap") : t("place.ask")}</h1>
      <div className="mt-6 max-w-2xl">
        <SearchBox autoFocus large showExamples={mode === "place"}
          onPick={mode === "lake" ? (r) => mapRef.current?.flyTo({ center: [r.lon, r.lat], zoom: 14, duration: 900 }) : undefined} />
      </div>
      <h2 className="mt-12 text-[1.6rem]">{t("search.pickTitle")}</h2>
      <p className="muted mt-1">{t("search.pickHint")}</p>
      <div className="relative mt-4 h-[60vh] min-h-[360px] overflow-hidden rounded-xl border border-line">
        <MapView className="absolute inset-0" center={center} zoom={start ? 15 : mode === "lake" ? 12 : 11} satellite={mode === "lake" || !!start}
          onReady={(m) => { mapRef.current = m; m.on("moveend", () => { const c = m.getCenter(); setCenter([c.lng, c.lat]); }); }} />
        <Crosshair size={34} strokeWidth={2.4} className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-built" />
        <div className="absolute inset-x-3 bottom-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-paper/95 px-4 py-3 shadow">
          <span className="num">{center[1].toFixed(4)} N, {center[0].toFixed(4)} E</span>
          <button className="btn-primary" onClick={() => goTo(center[1], center[0])}>{mode === "lake" ? t("explore.analyseHere") : t("search.pickGo")}</button>
        </div>
      </div>
    </div>
  );
}

export default function Place() {
  const [sp] = useSearchParams();
  const lat = Number(sp.get("lat"));
  const lon = Number(sp.get("lon"));
  const valid = !!sp.get("lat") && !!sp.get("lon") && !Number.isNaN(lat) && !Number.isNaN(lon);
  if (!valid || sp.get("pick")) return <Picker mode={sp.get("pick") === "lake" ? "lake" : "place"} start={valid ? [lon, lat] : undefined} />;
  return <Report key={`${lat},${lon}`} lat={lat} lon={lon} label={sp.get("label") ?? undefined} />;
}

function Report({ lat, lon, label }: { lat: number; lon: number; label?: string }) {
  const { t, lang } = useT();
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<PlaceResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [persona, setPersona] = usePersona();
  const { user, openAuth } = useAuth();
  const qc = useQueryClient();
  const started = useRef(false);
  const { data: job } = useJob(jobId);
  const { data: areas } = useAreas();
  const { data: act } = useActivity(!!user);

  async function start(fresh = false) {
    setError(null);
    setResult(null);
    setJobId(null);
    try {
      const r = await api.post<any>("/v1/places", { lat, lon, label, fresh });
      if (r.status === "done") setResult(r.result);
      else setJobId(r.jobId);
    } catch (e: any) {
      setError(e instanceof ApiError && e.status === 400 ? t("place.outside") : e.message);
    }
  }
  useEffect(() => { if (!started.current) { started.current = true; start(); } }, []);
  useEffect(() => {
    if (job?.status === "done" && job.result) setResult(job.result);
    if (job?.status === "failed") setError(job.error ?? "failed");
  }, [job?.status]);

  const live = result ?? null;
  const signals = live?.signals ?? job?.static?.signals;
  const frames = live?.frames ?? job?.optical?.frames ?? [];
  const sightings = (live?.signals?.radarSightings ?? job?.radar?.sightings ?? []) as { date: string; haCore: number }[];
  const scenes = live?.radar?.scenesChecked ?? job?.radar?.scenesChecked;
  const areaId = live?.areaId ?? job?.static?.areaId ?? undefined;
  const area = areas?.find((a) => a.id === areaId);
  const { data: man } = useManifest(area);
  const placeName = label ?? live?.label?.label ?? job?.static?.label?.label;
  const findings: Finding[] = live?.findings ?? (signals ? metricsFindingsPlace({ ...signals, radarSightings: sightings }) : []);
  const heat = live ? live.heat : job?.heat;
  const nepal = (live?.country ?? area?.country) === "NP";
  const [answers] = useAnswers();
  const report = usePlaceReport(lat, lon, placeName, persona, persona === "home" ? answers : undefined);
  const gh = geohash(lat, lon);
  const following = !!act?.follows?.some((f) => f.gh7 === gh);
  const tlFrames = useMemo(() => frames.map((f) => ({
    key: String(f.season), label: String(f.season), url: f.url,
    sub: `${f.source === "LS" ? "Landsat" : "Sentinel-2"}, ${day(f.date, lang)}, ${t("place.waterShare", { pct: Math.round(100 * f.waterShare300) })}`,
  })), [frames, lang]);
  const shareText = placeName && live?.memory.index != null
    ? t("share.place", { place: placeName, tier: t(`place.memory.${live.memory.tier}` as any), n: live.memory.index })
    : t("share.placeNoIndex", { place: placeName ?? `${lat.toFixed(4)} N, ${lon.toFixed(4)} E` });

  async function followNow() {
    if (!user) { openAuth("signin", t("auth.needed")); return; }
    try {
      await api.spost("/v1/secure/follows", { lat, lon, label: placeName, lang });
      await qc.invalidateQueries({ queryKey: ["activity"] });
    } catch { /* the rain panel shows the reason when it is tried there */ }
  }

  const steps = [
    { label: t("place.step.static"), state: signals ? "done" : "running" },
    { label: t("place.step.optical"), state: job?.optical || live ? "done" : "running" },
    { label: t("place.step.radar"), state: job?.radar || live ? "done" : "running" },
    { label: t("heat.title"), state: job?.heat || live ? "done" : "running" },
    { label: t("place.step.score"), state: live ? "done" : "waiting" },
  ] as const;

  const stepExtra = (a: Action) => {
    if (a.key === "act.home.report") return <button className="btn-quiet px-3 py-1.5 text-[14px]" onClick={report.start} disabled={report.state.s === "working"}><FileSignature size={15} />{t("week.do.report")}</button>;
    if (a.key === "act.home.follow" || a.key === "act.res.follow") return following
      ? <span className="inline-flex items-center gap-1.5 text-[14px] font-semibold text-live"><Check size={15} />{t("week.do.following")}</span>
      : <button className="btn-quiet px-3 py-1.5 text-[14px]" onClick={followNow}><BellRing size={15} />{t("week.do.follow")}</button>;
    if (a.key === "act.res.report") return <Link className="btn-quiet px-3 py-1.5 text-[14px]" to={`/waterlogging?report=1&lat=${lat.toFixed(5)}&lon=${lon.toFixed(5)}`}><Camera size={15} />{t("week.do.reportWater")}</Link>;
    if (a.key === "act.res.lake") return <Link className="btn-quiet px-3 py-1.5 text-[14px]" to={`/lake/find?lat=${lat.toFixed(5)}&lon=${lon.toFixed(5)}`}><Waves size={15} />{t("week.do.lake")}</Link>;
    return null;
  };

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="muted text-[15px]">{t("place.title")}</p>
          <h1 className="mt-1 max-w-[22ch] text-[clamp(2.1rem,4.6vw,3.4rem)]">{placeName ?? `${lat.toFixed(4)} N, ${lon.toFixed(4)} E`}</h1>
          <p className="num mt-2 text-[1rem] text-ink-2">{lat.toFixed(5)} N, {lon.toFixed(5)} E{live ? `, ${t("place.checkedOn", { date: day(live.checkedAt, lang) })}` : ""}</p>
        </div>
        {live && <button className="btn-ghost" onClick={() => start(true)}><RotateCcw size={16} /> {t("place.recheck")}</button>}
      </div>
      {live && (
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <ReportButton state={report.state} start={report.start} />
          <ShareButtons text={shareText} />
          <ListenButton body={{ kind: "place", lat, lon, persona }} />
        </div>
      )}
      <ReportStatus state={report.state} />

      {error && <div className="mt-6"><ErrorNote>{t("place.failed", { msg: error })}</ErrorNote></div>}

      <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] [&>*]:min-w-0">
        <div className="min-w-0 space-y-9">
          {live ? (
            <div>
              <MemoryGauge index={live.memory.index} tier={live.memory.tier} />
              <p className="mt-4 max-w-prose text-[15.5px] text-ink-2">{t("place.memory.explain")}</p>
              <p className="mt-2 max-w-prose text-[14px] text-ink-2">{t("place.memory.validation")} <Link className="link" to="/about#validation">{t("footer.methods")}</Link></p>
            </div>
          ) : !error && (
            <div className="rounded-xl border border-line p-5">
              <p className="mb-4 font-semibold">{t("place.checking")}</p>
              <Progress steps={steps as any} />
            </div>
          )}
          {live && <VerdictCard lat={lat} lon={lon} persona={persona} onPersona={setPersona} />}
          {live && <RainStrip lat={lat} lon={lon} label={placeName} tier={live.memory.tier} nepal={nepal} />}
          {live?.actions && <ThisWeek actions={live.actions} persona={persona} onPersona={setPersona} placeKey={gh} extra={stepExtra} />}
          {findings.length > 0 && (
            <div>
              <h2 className="text-[1.7rem]">{t("place.findings")}</h2>
              <div className="mt-2"><FindingList findings={findings} /></div>
            </div>
          )}
          {(job?.radar || live) && (
            <div>
              <h3>{t("place.radar.title")}</h3>
              {sightings.length ? (
                <>
                  <p className="muted mt-1 text-[14.5px]">{t("place.radar.some", { n: sightings.length, scenes: scenes ?? "-" })}</p>
                  <ul className="mt-3 flex flex-wrap gap-2">
                    {sightings.map((s) => <li key={s.date} className="tag bg-built/10 text-[13.5px] text-built">{day(s.date, lang)}, {ha(s.haCore)} {t("common.ha")}</li>)}
                  </ul>
                </>
              ) : <p className="muted mt-1 text-[15px]">{t("place.radar.none", { n: scenes ?? 0 })}</p>}
            </div>
          )}
          {signals && (
            <div>
              <h3>{t("place.numbers")}</h3>
              <dl className="mt-2 divide-y divide-line text-[15px]">
                {([
                  ["occurrenceHere", `${ha(signals.occurrenceHere)} ${t("unit.pctLooks")}`],
                  ["everWater1000", `${ha(100 * signals.everWater1000)}%`],
                  ["lostWater1000", `${ha(100 * signals.lostWater1000)}%`],
                  ["builtOverWaterHa2000", `${ha(signals.builtOverWaterHa2000)} ${t("common.ha")}`],
                  ["depressionMax300", `${ha(signals.depressionMax300)} ${t("unit.m")}`],
                  ["handMin300", `${ha(signals.handMin300)} ${t("unit.m")}`],
                  ["nearestWaterM", signals.nearestWaterM != null ? `${ha(signals.nearestWaterM, 0)} ${t("unit.m")}` : "-"],
                  ["elevationM", `${ha(signals.elevationM, 0)} ${t("unit.m")}`],
                  ["landCoverHere", t(`io.${signals.landCoverHere ?? "unknown"}` as any)],
                ] as const).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4 py-2">
                    <dt className="text-ink-2">{t(`signal.${k}` as any)}</dt>
                    <dd className="num shrink-0 text-right">{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </div>
        <div className="min-w-0 space-y-10">
          {tlFrames.length > 0 ? (
            <div>
              <h2 className="mb-3 text-[1.7rem]">{t("place.timelapse")}</h2>
              <div className="max-w-[640px]"><Timelapse frames={tlFrames} aspect="1 / 1" start="last" marker /></div>
            </div>
          ) : !error && !live && <div className="skeleton aspect-square w-full max-w-[640px]" />}
          {(heat || live) && <div className="max-w-[640px]"><HeatPanel heat={heat} older={!!live && live.heat === undefined} /></div>}
          {live && <div className="max-w-[640px]"><PeopleReports lat={lat} lon={lon} /></div>}
          <div className="relative h-[380px] overflow-hidden rounded-xl border border-line">
            <MapView className="absolute inset-0" center={[lon, lat]} zoom={13.2} marker={[lon, lat]}
              memory={man?.layers.memory ? { url: man.layers.memory.url, corners: man.layers.memory.corners, opacity: 0.85 } : null}
              lakesUrl={man?.lakesUrl ?? null} />
          </div>
        </div>
      </div>
    </div>
  );
}
