import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, Camera, FileSearch, FileSignature, Loader2, MapPin, ShieldCheck, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ErrorNote, FindingList, GradePlate, SeriesChart, Spinner, Stat } from "../components/bits";
import { LakeNewsAndRecord, LakeWhy } from "../components/LakeInsights";
import ListenButton from "../components/ListenButton";
import MapView from "../components/MapView";
import RtiDialog, { RtiList } from "../components/RtiDialog";
import ShareButtons from "../components/ShareButtons";
import Timelapse, { useLakeFrames } from "../components/Timelapse";
import { api, uploadToS3 } from "../lib/api";
import { useAuth } from "../lib/auth";
import { day, dateTime, ha, pct, shortHash } from "../lib/format";
import { useT } from "../lib/i18n";
import { useAreas, useEvidence, useLake, useLakeDossiers, useLakeRti, useLedger, useManifest } from "../lib/queries";
import type { Evidence, Lake } from "../lib/types";

const LANGS: [string, string][] = [["hi", "हिन्दी"], ["kn", "ಕನ್ನಡ"], ["ta", "தமிழ்"], ["te", "తెలుగు"], ["ml", "മലയാളം"], ["mr", "मराठी"],
  ["bn", "বাংলা"], ["gu", "ગુજરાતી"], ["pa", "ਪੰਜਾਬੀ"], ["ur", "اردو"], ["ne", "नेपाली"], ["as", "অসমীয়া"], ["or", "ଓଡ଼ିଆ"]];

function Replaced({ lake }: { lake: Lake }) {
  const { t } = useT();
  const rb = lake.metrics.replacedBy ?? {};
  const total = Object.values(rb).reduce((a, b) => a + b, 0);
  if (total < 0.3) return null;
  const order: [string, string][] = [["built", "bg-built"], ["bare", "bg-lost"], ["crops", "bg-[#B8A13A]"], ["vegetation", "bg-[#4E8F4A]"], ["water", "bg-memory"]];
  return (
    <div>
      <h3>{t("lake.replaced")}</h3>
      <div className="mt-3 flex h-4 w-full overflow-hidden rounded-sm">
        {order.filter(([k]) => rb[k] > 0).map(([k, c]) => <div key={k} className={c} style={{ width: `${(100 * rb[k]) / total}%` }} title={`${ha(rb[k])} ${t("common.ha")}`} />)}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[14px] text-ink-2">
        {order.filter(([k]) => rb[k] > 0).map(([k, c]) => (
          <li key={k} className="flex items-center gap-1.5"><i className={`inline-block h-2.5 w-2.5 rounded-sm ${c}`} />{t(`lc.${k}` as any, { ha: ha(rb[k]) })}</li>
        ))}
      </ul>
    </div>
  );
}

/** Where the name came from: a map's own name, or (when no map names it) what it was named after. */
function nameNote(src: string, t: ReturnType<typeof useT>["t"]) {
  if (src === "OpenStreetMap" || src === "GeoNames") return t("lake.nameFrom", { src });
  if (src === "nearby-lake") return t("lake.nameNearLake");
  if (src === "area") return t("lake.nameArea");
  return t("lake.namePlace");
}

function EvidenceCard({ e }: { e: Evidence }) {
  const { t, lang } = useT();
  const statusColor = e.status === "verified" ? "bg-live/15 text-live" : e.status === "rejected" ? "bg-built/10 text-built" : "bg-paper-3 text-ink-2";
  return (
    <figure className="overflow-hidden rounded-lg border border-line">
      <a href={e.url} target="_blank" rel="noreferrer" className="block aspect-[4/3] bg-paper-3">
        {e.thumbUrl && <img src={e.thumbUrl} alt={e.ai?.summary ?? (e.categories ?? []).join(", ")} className="h-full w-full object-cover" loading="lazy" />}
      </a>
      <figcaption className="space-y-1.5 p-3 text-[13.5px]">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={`tag ${statusColor}`}>{t(`ev.status.${e.status}` as any)}</span>
          {(e.categories ?? []).filter((c) => c !== "other").map((c) => <span key={c} className="tag bg-paper-2 text-ink">{t(`cat.${c}` as any)}</span>)}
        </div>
        {e.ai?.summary && <p className="text-ink-2"><span className="font-semibold text-ink">{t("ev.ai")}:</span> {e.ai.summary}</p>}
        {e.note && <p>“{e.note}”</p>}
        <p className="text-ink-2"><MapPin size={13} className="mr-1 inline" />{t(`ev.gps.${e.gpsCheck ?? "none"}` as any)}, {day(e.capturedAt ?? e.createdAt, lang)}, {t("ev.by", { who: e.uploader ?? "-" })}</p>
        {e.review && <p className="text-ink-2"><ShieldCheck size={13} className="mr-1 inline" />{e.review.by}: {e.review.note}</p>}
        <p className="num text-[12px] text-ink-2">{t("ev.fingerprint")} {shortHash(e.sha256, 16)}</p>
      </figcaption>
    </figure>
  );
}

function UploadDialog({ lake, open, onClose }: { lake: Lake; open: boolean; onClose: () => void }) {
  const { t } = useT();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState("");
  const [state, setState] = useState<"idle" | "uploading" | "processing" | "done" | "unrelated" | "error">("idle");
  const [msg, setMsg] = useState<string | null>(null);
  const [saw, setSaw] = useState<string | null>(null);
  const [reason, setReason] = useState<string>("other");
  const preview = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => { if (!open) { setFile(null); setNote(""); setState("idle"); setMsg(null); setSaw(null); } }, [open]);

  function choose(f: File | null) {
    setFile(f);
    if (state === "unrelated" || state === "error") { setState("idle"); setMsg(null); setSaw(null); }
  }

  async function go() {
    if (!file) return;
    if (file.size > 12 * 1024 * 1024) { setState("error"); setMsg(t("ev.tooBig")); return; }
    setState("uploading");
    setSaw(null);
    try {
      const ctype = ["image/png", "image/webp"].includes(file.type) ? file.type : "image/jpeg";
      const r = await api.spost<{ evidenceId: string; upload: { url: string; fields: Record<string, string> } }>(
        `/v1/secure/lakes/${lake.lakeId}/evidence/upload`, { contentType: ctype, size: file.size, note: note || undefined });
      await uploadToS3(r.upload, file);
      setState("processing");
      for (let i = 0; i < 30; i++) {
        await new Promise((res) => setTimeout(res, 2500));
        const e = await api.sget<any>(`/v1/secure/evidence/${r.evidenceId}`).catch(() => null);
        if (e && e.status && e.status !== "uploading") {
          if (e.status === "blocked") { setState("error"); setMsg(t("ev.blocked")); return; }
          setSaw(e.ai?.summary ?? null);
          if (e.status === "unrelated") {
            setReason(["text", "graphic", "indoor"].includes(e.unrelatedReason) ? e.unrelatedReason : "other");
            setState("unrelated");
            return;
          }
          setState("done");
          qc.invalidateQueries({ queryKey: ["evidence", lake.lakeId] });
          qc.invalidateQueries({ queryKey: ["ledger", lake.lakeId] });
          return;
        }
      }
      setState("done");
    } catch (e: any) {
      setState("error");
      setMsg(e.decision?.rule ?? e.message);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-[rgb(6_12_24/0.55)]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(94vw,520px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-line bg-paper p-6 shadow-2xl">
          <div className="flex items-start justify-between">
            <Dialog.Title className="display text-[1.8rem]">{t("ev.title")}</Dialog.Title>
            <Dialog.Close className="btn-ghost -mr-2" aria-label={t("common.close")}><X size={18} /></Dialog.Close>
          </div>
          <Dialog.Description className="muted mt-1 text-[15px]">{lake.name}. {t("ev.hint")}</Dialog.Description>
          <label className="mt-4 grid aspect-[4/3] cursor-pointer place-items-center overflow-hidden rounded-lg border-2 border-dashed border-line bg-paper-2 hover:border-memory">
            {preview ? <img src={preview} alt="" className="h-full w-full object-cover" /> : <span className="flex items-center gap-2 text-ink-2"><Camera size={20} />{t("ev.choose")}</span>}
            <input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" className="sr-only" onChange={(e) => choose(e.target.files?.[0] ?? null)} />
          </label>
          <label className="label mt-4" htmlFor="ev-note">{t("ev.note")}</label>
          <textarea id="ev-note" className="field min-h-[80px]" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
          <p className="muted mt-3 text-[13.5px]">{t("ev.privacy")}</p>
          {state === "done" && (
            <div role="status" className="mt-3 rounded-md bg-live/10 px-3 py-2 text-[15px] text-live">
              <p>{t("ev.done")}</p>
              {saw && <p className="mt-1 text-[14px] text-ink-2">{t("ev.saw", { summary: saw })}</p>}
            </div>
          )}
          {state === "unrelated" && (
            <div role="alert" className="mt-3 rounded-md border border-lost/40 bg-lost/10 px-3 py-2.5 text-[15px]">
              <p className="font-semibold">{t("ev.unrelated.title")}</p>
              <p className="mt-1">{t(`ev.unrelated.${reason}` as any)}</p>
              {saw && <p className="mt-1 text-[14px] text-ink-2">{t("ev.saw", { summary: saw })}</p>}
              <p className="mt-1 text-[14px] text-ink-2">{t("ev.unrelated.next")}</p>
            </div>
          )}
          {state === "error" && <div className="mt-3"><ErrorNote>{msg}</ErrorNote></div>}
          <div className="mt-5 flex justify-end gap-2">
            <button className="btn-ghost" onClick={onClose}>{t("common.close")}</button>
            <button className="btn-primary" disabled={!file || state === "uploading" || state === "processing" || state === "done" || state === "unrelated"} onClick={go}>
              {(state === "uploading" || state === "processing") && <Loader2 size={16} className="animate-spin" />}
              {state === "uploading" ? t("ev.uploading") : state === "processing" ? t("ev.processing") : t("ev.upload")}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function DossierDialog({ lake, open, onClose }: { lake: Lake; open: boolean; onClose: () => void }) {
  const { t } = useT();
  const nav = useNavigate();
  const auths = lake.authorities.filter((a) => a.kind !== "court");
  const [rec, setRec] = useState(auths[0]?.id ?? "");
  const [lang, setLang] = useState(lake.area?.lang && lake.area.lang !== "en" ? lake.area.lang : "hi");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.spost<{ dossierId: string }>(`/v1/secure/lakes/${lake.lakeId}/dossiers`, { recipientId: rec, language: lang });
      nav(`/dossier/${r.dossierId}`);
    } catch (e: any) {
      setErr(e.decision?.rule ?? e.message);
      setBusy(false);
    }
  }
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-[rgb(6_12_24/0.55)]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(94vw,520px)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line bg-paper p-6 shadow-2xl">
          <div className="flex items-start justify-between">
            <Dialog.Title className="display text-[1.8rem]">{t("ds.title")}</Dialog.Title>
            <Dialog.Close className="btn-ghost -mr-2" aria-label={t("common.close")}><X size={18} /></Dialog.Close>
          </div>
          <Dialog.Description className="muted mt-1 text-[15px]">{t("ds.contains")}</Dialog.Description>
          <label className="label mt-5" htmlFor="ds-rec">{t("ds.recipient")}</label>
          <select id="ds-rec" className="field" value={rec} onChange={(e) => setRec(e.target.value)}>
            {auths.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <label className="label mt-4" htmlFor="ds-lang">{t("ds.language")}</label>
          <select id="ds-lang" className="field" value={lang} onChange={(e) => setLang(e.target.value)}>
            {LANGS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>
          {err && <div className="mt-3"><ErrorNote>{err}</ErrorNote></div>}
          <div className="mt-6 flex justify-end gap-2">
            <button className="btn-ghost" onClick={onClose}>{t("common.cancel")}</button>
            <button className="btn-memory" onClick={go} disabled={busy || !rec}>
              {busy && <Loader2 size={16} className="animate-spin" />}<FileSignature size={16} /> {t("ds.create")}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default function LakePage() {
  const { lakeId } = useParams();
  const { t, lang } = useT();
  const { user, openAuth } = useAuth();
  const qc = useQueryClient();
  const { data: lake, isLoading, error } = useLake(lakeId);
  const { data: evidence } = useEvidence(lakeId);
  const { data: dossiers } = useLakeDossiers(lakeId);
  const { data: ledger } = useLedger(lakeId);
  const { data: rtis } = useLakeRti(lakeId);
  const { data: areas } = useAreas();
  const { data: man } = useManifest(areas?.find((a) => a.id === lake?.areaId));
  const frames = useLakeFrames(lake?.lakeId, lake?.frames, lake?.latestDate, lake?.frameUrls);
  const [upload, setUpload] = useState(false);
  const [dossier, setDossier] = useState(false);
  const [rti, setRti] = useState(false);
  const [watchMsg, setWatchMsg] = useState<string | null>(null);

  if (isLoading) return <div className="mx-auto max-w-[1400px] px-6 py-16"><Spinner label={t("common.loading")} /></div>;
  if (error || !lake) return <div className="mx-auto max-w-[1400px] px-6 py-16"><ErrorNote>{t("lake.notFound")}</ErrorNote></div>;
  const m = lake.metrics;
  const need = (fn: () => void) => (user ? fn() : openAuth("signin", t("auth.needed")));
  const bbox = (() => {
    const coords: number[][] = (lake.geometry as any).type === "Polygon" ? (lake.geometry as any).coordinates[0] : (lake.geometry as any).coordinates.flat(1)[0] ?? [];
    const xs = coords.map((c) => c[0]), ys = coords.map((c) => c[1]);
    const pad = 0.004;
    return xs.length ? [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) + pad, Math.max(...ys) + pad] : undefined;
  })();

  async function watch(on: boolean) {
    try {
      const r = on ? await api.spost<any>(`/v1/secure/lakes/${lake!.lakeId}/watch`) : await api.sdel<any>(`/v1/secure/lakes/${lake!.lakeId}/watch`);
      setWatchMsg(on ? (r.status === "active" ? t("lake.watching") : t("lake.watchConfirm")) : null);
      qc.invalidateQueries({ queryKey: ["lake", lake!.lakeId] });
    } catch (e: any) {
      setWatchMsg(e.message);
    }
  }

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="flex items-start gap-5">
          <GradePlate grade={m.grade.grade} size="lg" />
          <div>
            <h1 className="text-[clamp(2.2rem,5vw,3.6rem)]">{lake.name}</h1>
            <p className="mt-2 text-[15.5px] text-ink-2">
              {lake.area ? <Link className="link" to={`/explore/${lake.area.id}`}>{lake.area.names[lang] ?? lake.area.names.en}</Link> : lake.admin?.state}
              {", "}{t(`grade.${m.grade.grade ?? "none"}` as any)}{", "}{t("lake.coords", { lat: lake.lat.toFixed(4), lon: lake.lon.toFixed(4) })}
              {lake.onDemand && <span className="tag ml-2 bg-paper-2">{t("lake.onDemand")}</span>}
            </p>
            {lake.nameSource && <p className="muted text-[13px]">{nameNote(lake.nameSource, t)}</p>}
          </div>
        </div>
        {/* Actions, then share and listen spread under them: the two rows form one block beside the title or below it. */}
        <div className="flex w-full flex-col gap-3 lg:w-auto">
          <div className="grid gap-2 sm:grid-cols-2 lg:flex lg:flex-wrap">
            <button className="btn-primary" onClick={() => need(() => setUpload(true))}><Camera size={17} /> {t("lake.addPhoto")}</button>
            <button className="btn-memory" onClick={() => need(() => setDossier(true))}><FileSignature size={17} /> {t("lake.createDossier")}</button>
            <button className="btn-quiet" onClick={() => need(() => watch(true))}><Bell size={17} /> {t("lake.watch")}</button>
            <button className="btn-quiet" onClick={() => setRti(true)}><FileSearch size={17} /> {t("rti.button")}</button>
          </div>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex flex-wrap gap-2">
              <ShareButtons text={t("share.lake", { lake: lake.name, grade: m.grade.grade ?? "-", label: t(`grade.${m.grade.grade ?? "none"}` as any) })} path={`/lake/${lake.lakeId}`} />
            </div>
            <ListenButton body={{ kind: "lake", lakeId: lake.lakeId }} />
          </div>
        </div>
      </div>
      {watchMsg && <p className="mt-3 text-[15px] text-memory">{watchMsg} {user && <button className="link ml-2 text-ink-2" onClick={() => watch(false)}><BellOff size={14} className="inline" /> {t("lake.unwatch")}</button>}</p>}

      <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] [&>*]:min-w-0">
        <div>
          <Timelapse frames={frames} aspect="1 / 1" start="last" />
        </div>
        <div className="min-w-0 space-y-8">
          <div className="grid grid-cols-2 gap-x-6 gap-y-7">
            <Stat label={t("lake.historic")} value={ha(m.historicHa)} unit={t("common.ha")} tone="memory" />
            <Stat label={t("lake.lost")} value={ha(m.lostHa)} unit={t("common.ha")} tone="lost" note={m.lostPct != null ? pct(m.lostPct) : undefined} />
            <Stat label={t("lake.built")} value={ha(m.builtHa ?? 0)} unit={t("common.ha")} tone="built" note={m.builtPct != null ? pct(m.builtPct) : undefined} />
            <Stat label={t("lake.retention")} value={m.retention.ratio != null ? pct(100 * m.retention.ratio) : "-"} note={t("lake.retentionExplain")} />
            {m.quality?.weedPct != null && <Stat label={t("lake.weeds")} value={pct(m.quality.weedPct)} note={day(m.quality.date, lang)} />}
            {m.storageLost?.millionLitresHigh > 0 && <Stat label={t("lake.storage")} value={`${ha(m.storageLost.millionLitresLow, 0)}-${ha(m.storageLost.millionLitresHigh, 0)}`} unit="ML" />}
          </div>
          <div>
            <h2 className="text-[1.7rem]">{t("lake.findings")}</h2>
            <div className="mt-1"><FindingList findings={lake.findings} /></div>
          </div>
        </div>
      </div>

      <LakeWhy lake={lake} on={{ photo: () => need(() => setUpload(true)), rti: () => setRti(true), watch: () => need(() => watch(true)),
        dossier: () => need(() => setDossier(true)) }} />

      <section className="mt-14 grid gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,4fr)] [&>*]:min-w-0">
        <div>
          <h2 className="text-[1.7rem]">{t("lake.series")}</h2>
          <div className="mt-4"><SeriesChart series={m.series} historicHa={m.historicHa} /></div>
        </div>
        <div className="min-w-0 space-y-8">
          <Replaced lake={lake} />
          <div>
            <h3>{t("lake.parts")}</h3>
            <ul className="mt-3 space-y-2.5">
              {m.grade.parts.map((p) => (
                <li key={p.key}>
                  <div className="flex justify-between text-[14.5px]"><span>{t(`lake.part.${p.key}` as any)}</span><span className="num">{Math.round(p.points)}/25</span></div>
                  <div className="mt-1 h-1.5 w-full rounded-full bg-paper-3"><div className="h-full rounded-full bg-memory" style={{ width: `${(100 * p.points) / 25}%` }} /></div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="mt-14">
        <div className="relative h-[420px] overflow-hidden rounded-xl border border-line">
          <MapView className="absolute inset-0" bbox={bbox} center={[lake.lon, lake.lat]} zoom={14}
            memory={man?.layers.memory ? { url: man.layers.memory.url, corners: man.layers.memory.corners, opacity: 0.85 } : null}
            lakesUrl={man?.lakesUrl ?? null} highlightLake={lake.lakeId} satellite />
        </div>
      </section>

      <section className="mt-14">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-[1.7rem]">{t("lake.evidence")}</h2>
          <button className="btn-quiet" onClick={() => need(() => setUpload(true))}><Camera size={16} /> {t("lake.addPhoto")}</button>
        </div>
        {evidence && evidence.length > 0 ? (
          <div className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-4 [&>*]:min-w-0">{evidence.map((e) => <EvidenceCard key={e.evidenceId} e={e} />)}</div>
        ) : <p className="muted mt-3 max-w-prose">{t("lake.evidenceEmpty")}</p>}
      </section>

      <LakeNewsAndRecord lake={lake} evidence={evidence} dossiers={dossiers} rtis={rtis} ledgerEntries={ledger?.entries.length} />

      <section className="mt-14 grid gap-10 lg:grid-cols-2 [&>*]:min-w-0">
        <div>
          <h2 className="text-[1.7rem]">{t("lake.dossiers")}</h2>
          {dossiers && dossiers.length > 0 ? (
            <ul className="mt-3 divide-y divide-line border-y border-line">
              {dossiers.map((d) => (
                <li key={d.dossierId}>
                  <Link to={`/dossier/${d.dossierId}`} className="flex items-center justify-between gap-4 py-3 hover:text-memory">
                    <span className="min-w-0"><span className="block truncate font-semibold">{d.recipient?.name}</span>
                      <span className="muted text-[13.5px]">{dateTime(d.createdAt, lang)}, {d.creator}</span></span>
                    <span className="tag shrink-0 bg-paper-2">{t(`dossier.status.${d.status}` as any)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : <p className="muted mt-3">{t("lake.dossiersEmpty")}</p>}
          <div className="mt-12 flex flex-wrap items-end justify-between gap-3">
            <h2 className="text-[1.7rem]">{t("rti.list.title")}</h2>
            <button className="btn-quiet" onClick={() => setRti(true)}><FileSearch size={16} /> {t("rti.button")}</button>
          </div>
          {rtis && rtis.length > 0 ? <RtiList items={rtis} /> : <p className="muted mt-3">{t("rti.list.empty")}</p>}
          <h3 className="mt-10">{t("lake.authorities")}</h3>
          <ul className="mt-2 space-y-1.5 text-[15px]">
            {lake.authorities.map((a) => <li key={a.id}>{a.url ? <a className="link" href={a.url} target="_blank" rel="noreferrer">{a.name}</a> : a.name}</li>)}
          </ul>
          <h3 className="mt-8">{t("lake.laws")}</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-[15px] text-ink-2">{lake.laws.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
        <div>
          <h2 className="text-[1.7rem]">{t("lake.ledger")}</h2>
          {ledger && (
            <>
              <p className={`mt-2 text-[15px] ${ledger.entries.length === 0 ? "text-ink-2" : ledger.verification.ok ? "text-live" : "text-built"}`}>
                {ledger.entries.length === 0 ? t("lake.ledgerEmpty") : ledger.verification.ok ? t("lake.ledgerOk", { n: ledger.entries.length }) : t("lake.ledgerBroken", { n: ledger.verification.brokenAt ?? "?" })}
              </p>
              <ol className="mt-3 space-y-2">
                {ledger.entries.slice(-12).reverse().map((e: any) => (
                  <li key={e.seq} className="rounded-md bg-paper-2 px-3 py-2 text-[13.5px]">
                    <div className="flex justify-between gap-3"><span className="font-semibold">#{e.seq} {e.kind}</span><span className="muted">{dateTime(e.at, lang)}</span></div>
                    <div className="num mt-0.5 break-all text-[12px] text-ink-2">{e.hash}</div>
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>
      </section>
      <UploadDialog lake={lake} open={upload} onClose={() => setUpload(false)} />
      <DossierDialog lake={lake} open={dossier} onClose={() => setDossier(false)} />
      <RtiDialog key={lake.lakeId} lake={lake} open={rti} onClose={() => setRti(false)} />
    </div>
  );
}
