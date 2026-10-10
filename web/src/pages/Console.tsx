import * as Tabs from "@radix-ui/react-tabs";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, History, Loader2, MapPin, ShieldAlert, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorNote, Spinner } from "../components/bits";
import { placeUrl } from "../components/SearchBox";
import { DepthTag, StatusTag } from "../components/WaterReportDialog";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dateTime, day, shortHash } from "../lib/format";
import { useT } from "../lib/i18n";
import { useAreas, useMe } from "../lib/queries";
import type { AuditEntry, Dossier, Evidence, WaterReport } from "../lib/types";

type Outcome = { ok: true } | { ok: false; rule: string; policies?: string[] } | null;

function Denied({ o }: { o: Outcome }) {
  const { t } = useT();
  if (!o) return null;
  if (o.ok) return <p className="text-[14.5px] text-live"><Check size={15} className="mr-1 inline" />{t("console.recorded")}</p>;
  return (
    <div role="alert" className="rounded-md border border-built/40 bg-built/5 px-3 py-2 text-[14.5px]">
      <p><ShieldAlert size={15} className="mr-1.5 inline text-built" />{t("console.denied", { rule: o.rule })}</p>
      {o.policies && o.policies.length > 0 && <p className="muted mt-0.5 text-[13px]">{t("console.decidedBy", { rules: o.policies.join(", ") })}</p>}
    </div>
  );
}

function outcomeOf(e: any): Outcome {
  if (e instanceof ApiError && e.status === 403) return { ok: false, rule: e.decision?.rule ?? e.message, policies: e.decision?.policies };
  return { ok: false, rule: e?.message ?? String(e) };
}

function EvidenceItem({ e, canReview, onDone }: { e: Evidence; canReview: boolean; onDone: () => void }) {
  const { t, lang } = useT();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [out, setOut] = useState<Outcome>(null);
  async function review(decision: "verified" | "rejected") {
    setBusy(decision);
    setOut(null);
    try {
      await api.spost(`/v1/secure/evidence/${e.evidenceId}/review`, { decision, note });
      setOut({ ok: true });
      onDone();
    } catch (ex) {
      setOut(outcomeOf(ex));
    } finally {
      setBusy(null);
    }
  }
  const tone = e.status === "verified" ? "bg-live/15 text-live" : e.status === "rejected" ? "bg-built/10 text-built" : "bg-lost/15 text-ink";
  return (
    <li className="grid gap-4 py-5 sm:grid-cols-[180px_minmax(0,1fr)]">
      <a href={e.url} target="_blank" rel="noreferrer" className="block aspect-[4/3] overflow-hidden rounded-md bg-paper-3">
        {e.thumbUrl && <img src={e.thumbUrl} alt={e.ai?.summary ?? ""} className="h-full w-full object-cover" loading="lazy" />}
      </a>
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Link to={`/lake/${e.lakeId}`} className="text-[16.5px] font-semibold hover:text-memory">{e.lakeName ?? e.lakeId}</Link>
          <span className={`tag ${tone}`}>{t(`ev.status.${e.status}` as any)}</span>
          {(e.categories ?? []).filter((c) => c !== "other").map((c) => <span key={c} className="tag bg-paper-2">{t(`cat.${c}` as any)}</span>)}
        </div>
        {e.ai?.summary && <p className="text-[14.5px] text-ink-2"><span className="font-semibold text-ink">{t("ev.ai")}:</span> {e.ai.summary}</p>}
        {e.note && <p className="text-[15px]">“{e.note}”</p>}
        <p className="text-[14px] text-ink-2">
          <MapPin size={14} className="mr-1 inline" />{t(`ev.gps.${e.gpsCheck ?? "none"}` as any)}
          {e.gpsDistanceM != null && e.gpsDistanceM > 0 ? ` (${t("console.distance", { m: e.gpsDistanceM })})` : ""}
          {", "}{t("console.uploaded", { date: dateTime(e.createdAt, lang), who: e.uploader ?? "-" })}
        </p>
        <p className="num text-[12px] text-ink-2">{t("ev.fingerprint")} {shortHash(e.sha256, 20)}</p>
        {e.review && (
          <p className="text-[14px]"><span className="font-semibold">{t(`ev.status.${e.review.decision}` as any)}</span>, {e.review.by}, {dateTime(e.review.at, lang)}: {e.review.note}</p>
        )}
        {canReview && e.status === "new" && (
          <div className="pt-1">
            <label className="label" htmlFor={`note-${e.evidenceId}`}>{t("console.note")}</label>
            <textarea id={`note-${e.evidenceId}`} className="field min-h-[64px] text-[15px]" maxLength={600} value={note} onChange={(x) => setNote(x.target.value)} />
            <p className="muted mt-1 text-[12.5px]">{t("console.noteHint")}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <button className="btn-primary px-3 py-2" disabled={!!busy || note.trim().length < 10} onClick={() => review("verified")}>
                {busy === "verified" ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}{t("console.verify")}
              </button>
              <button className="btn-quiet px-3 py-2" disabled={!!busy || note.trim().length < 10} onClick={() => review("rejected")}>
                {busy === "rejected" ? <Loader2 size={15} className="animate-spin" /> : <X size={15} />}{t("console.reject")}
              </button>
            </div>
          </div>
        )}
        <Denied o={out} />
      </div>
    </li>
  );
}

function WaterItem({ r, canReview, onDone }: { r: WaterReport; canReview: boolean; onDone: () => void }) {
  const { t, lang } = useT();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [out, setOut] = useState<Outcome>(null);              // refusals only: a report has no lake ledger
  const [decided, setDecided] = useState<"verified" | "rejected" | null>(null);
  async function review(decision: "verified" | "rejected") {
    setBusy(decision);
    setOut(null);
    try {
      await api.spost(`/v1/secure/waterlogging/${r.reportId}/review`, { decision, note });
      setDecided(decision);
      setNote("");
      onDone();
    } catch (ex) {
      setOut(outcomeOf(ex));
    } finally {
      setBusy(null);
    }
  }
  const ai = r.ai;
  const seen = ai && (ai.summary || ai.waterVisible != null);
  return (
    <li className="grid gap-4 py-5 sm:grid-cols-[180px_minmax(0,1fr)]">
      {r.url ? (
        <a href={r.url} target="_blank" rel="noreferrer" aria-label={t("wl.openPhoto")} className="block aspect-[4/3] overflow-hidden rounded-md bg-paper-3">
          {r.thumbUrl && <img src={r.thumbUrl} alt={ai?.summary ?? ""} className="h-full w-full object-cover" loading="lazy" />}
        </a>
      ) : <div className="aspect-[4/3] rounded-md bg-paper-3" />}
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Link to={placeUrl({ lat: r.lat, lon: r.lon })} className="num text-[16.5px] hover:text-memory">{t("lake.coords", { lat: r.lat.toFixed(4), lon: r.lon.toFixed(4) })}</Link>
          <StatusTag status={r.status} />
          <DepthTag depth={r.depth} />
        </div>
        {seen && (
          <p className="text-[14.5px] text-ink-2">
            <span className="font-semibold text-ink">{t("wl.ai")}:</span>{" "}
            {ai!.waterVisible != null && (
              <span className={`font-semibold ${ai!.waterVisible ? "text-ink" : "text-built"}`}>
                {t(ai!.waterVisible ? "wl.ai.water" : "wl.ai.noWater")}{ai!.confidence != null ? ` (${Math.round(ai!.confidence * 100)}%)` : ""}.{" "}
              </span>
            )}
            {ai!.summary}
          </p>
        )}
        {r.note && <p className="text-[15px]">“{r.note}”</p>}
        <p className="text-[14px] text-ink-2">
          <MapPin size={14} className="mr-1 inline" aria-hidden="true" />{t(r.locationSource === "photo" ? "wl.loc.photo" : "wl.loc.device")}
          {", "}{t("console.uploaded", { date: dateTime(r.createdAt, lang), who: r.uploader ?? "-" })}
        </p>
        {r.locationMismatch && <p className="text-[14px]"><AlertTriangle size={14} className="mr-1 inline text-lost" aria-hidden="true" />{t("wl.loc.mismatch")}</p>}
        {r.oldPhoto && r.capturedAt && <p className="text-[14px]"><History size={14} className="mr-1 inline text-lost" aria-hidden="true" />{t("wl.oldPhoto", { date: day(r.capturedAt, lang) })}</p>}
        {r.review && (
          <p className="text-[14px]"><span className="font-semibold">{t(`wl.status.${r.review.decision}` as any)}</span>, {r.review.by}, {dateTime(r.review.at, lang)}: {r.review.note}</p>
        )}
        {canReview && !decided && (r.status === "live" || r.status === "hidden") && (
          <div className="pt-1">
            <label className="label" htmlFor={`wnote-${r.reportId}`}>{t("console.note")}</label>
            <textarea id={`wnote-${r.reportId}`} className="field min-h-[64px] text-[15px]" maxLength={600} value={note} onChange={(x) => setNote(x.target.value)} />
            <p className="muted mt-1 text-[12.5px]">{t("wl.noteHint")}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <button className="btn-primary px-3 py-2" disabled={!!busy || note.trim().length < 10} onClick={() => review("verified")}>
                {busy === "verified" ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}{t("console.verify")}
              </button>
              <button className="btn-quiet px-3 py-2" disabled={!!busy || note.trim().length < 10} onClick={() => review("rejected")}>
                {busy === "rejected" ? <Loader2 size={15} className="animate-spin" /> : <X size={15} />}{t("console.reject")}
              </button>
            </div>
          </div>
        )}
        {decided && <p role="status" className="text-[14.5px] text-live"><Check size={15} className="mr-1 inline" />{t(`wl.status.${decided}`)}</p>}
        <Denied o={out} />
      </div>
    </li>
  );
}

function DossierItem({ d, canRespond, onDone }: { d: Dossier; canRespond: boolean; onDone: () => void }) {
  const { t, lang } = useT();
  const [status, setStatus] = useState("acknowledged");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState<Outcome>(null);
  const open = ["submitted", "acknowledged", "action_taken"].includes(d.status);
  async function respond() {
    setBusy(true);
    setOut(null);
    try {
      await api.spost(`/v1/secure/dossiers/${d.dossierId}/respond`, { status, note });
      setOut({ ok: true });
      setNote("");
      onDone();
    } catch (ex) {
      setOut(outcomeOf(ex));
    } finally {
      setBusy(false);
    }
  }
  return (
    <li className="space-y-2 py-5">
      <div className="flex flex-wrap items-center gap-2">
        <Link to={`/lake/${d.lakeId}`} className="text-[16.5px] font-semibold hover:text-memory">{d.lakeName ?? d.lakeId}</Link>
        <span className="tag bg-paper-2">{t(`dossier.status.${d.status}` as any)}</span>
      </div>
      <p className="text-[14.5px] text-ink-2">{t("dossier.to")} {d.recipient?.name ?? "-"}, {t("dossier.by", { who: d.creator ?? "-" })}, {dateTime(d.createdAt, lang)}</p>
      {d.submission && <p className="text-[14.5px]">{t("console.submittedRef", { portal: d.submission.portal || "-", ref: d.submission.reference || "-" })}</p>}
      <div className="flex flex-wrap gap-3 text-[14.5px]">
        <Link className="link" to={`/dossier/${d.dossierId}`}>{t("console.openDossier")}</Link>
        {d.pdfUrl && <a className="link" href={d.pdfUrl} target="_blank" rel="noreferrer">PDF</a>}
        <Link className="link" to={`/verify/${d.dossierId}`}>{t("dossier.verify")}</Link>
      </div>
      {canRespond && open && (
        <div className="grid gap-2 pt-1 sm:grid-cols-[220px_minmax(0,1fr)]">
          <div>
            <label className="label" htmlFor={`st-${d.dossierId}`}>{t("console.statusTo")}</label>
            <select id={`st-${d.dossierId}`} className="field py-2 text-[15px]" value={status} onChange={(e) => setStatus(e.target.value)}>
              {(["acknowledged", "action_taken", "rejected", "closed"] as const).map((s) => <option key={s} value={s}>{t(`console.resp.${s}`)}</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor={`rn-${d.dossierId}`}>{t("console.note")}</label>
            <textarea id={`rn-${d.dossierId}`} className="field min-h-[64px] text-[15px]" maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
            <p className="muted mt-1 text-[12.5px]">{t("console.noteHint")}</p>
          </div>
          <div className="sm:col-start-2">
            <button className="btn-primary px-3 py-2" disabled={busy || note.trim().length < 10} onClick={respond}>
              {busy && <Loader2 size={15} className="animate-spin" />}{t("console.respond")}
            </button>
          </div>
        </div>
      )}
      <Denied o={out} />
    </li>
  );
}

function AuditList({ entries }: { entries: AuditEntry[] }) {
  const { t, lang } = useT();
  if (!entries.length) return <p className="muted py-6">{t("console.empty")}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-[14px]">
        <thead className="border-b border-line text-ink-2">
          <tr><th className="py-2 pr-4 font-semibold">{t("console.when")}</th><th className="py-2 pr-4 font-semibold">{t("console.who")}</th>
            <th className="py-2 pr-4 font-semibold">{t("console.action")}</th><th className="py-2 font-semibold">{t("console.decision")}</th></tr>
        </thead>
        <tbody className="divide-y divide-line">
          {entries.map((e) => (
            <tr key={e.SK} className="align-top">
              <td className="whitespace-nowrap py-2.5 pr-4 text-ink-2">{dateTime(e.SK.split("#")[0], lang)}</td>
              <td className="py-2.5 pr-4">{e.pseudonym ?? "-"}</td>
              <td className="py-2.5 pr-4"><span className="font-semibold">{e.action}</span>{e.resource && <span className="muted block text-[12.5px]">{e.resource.type} {e.resource.id}</span>}</td>
              <td className="py-2.5">
                <span className={`tag ${e.allowed ? "bg-live/15 text-live" : "bg-built/10 text-built"}`}>{e.allowed ? t("console.allowed") : t("console.deniedShort")}</span>
                {e.explanation && <span className="muted block text-[12.5px]">{e.explanation}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Console() {
  const { t, lang } = useT();
  const { user, openAuth, ready } = useAuth();
  const qc = useQueryClient();
  const { data: me, error: meError } = useMe(!!user);
  const { data: areas } = useAreas();
  const [area, setArea] = useState<string>("");
  const [tab, setTab] = useState("evidence");
  const tabList = useRef<HTMLDivElement>(null);
  const [probe, setProbe] = useState<Outcome>(null);
  useEffect(() => {   // the tab row scrolls on narrow phones: keep the open tab fully in sight
    const l = tabList.current;
    const a = l?.querySelector<HTMLElement>("[role=tab][data-state=active]");
    if (!l || !a) return;
    const lr = l.getBoundingClientRect(), ar = a.getBoundingClientRect();
    if (ar.left < lr.left) l.scrollLeft -= lr.left - ar.left + 8;
    else if (ar.right > lr.right) l.scrollLeft += ar.right - lr.right + 8;
  }, [tab]);
  const official = me && me.user.role !== "citizen";
  const allowedAreas = areas ? (me?.consoleAreas ?? []).filter((a) => a === "other" || areas.some((x) => x.id === a)) : [];
  useEffect(() => { if (!area && allowedAreas.length) setArea(allowedAreas[0]); }, [allowedAreas.join(","), area]);

  const queue = useQuery({
    queryKey: ["queue", area, tab], enabled: !!official && !!area && tab !== "audit",
    queryFn: () => api.sget<{ items: any[] }>(`/v1/secure/console/queue?area=${area}&type=${tab === "evidence" || tab === "waterlogging" ? tab : "dossiers"}`).then((r) => r.items),
  });
  const audit = useQuery({
    queryKey: ["audit", area], enabled: !!official && !!area && tab === "audit",
    queryFn: () => api.sget<{ entries: AuditEntry[] }>(`/v1/secure/console/audit?area=${area}`).then((r) => r.entries),
  });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["queue", area] }); qc.invalidateQueries({ queryKey: ["audit", area] }); };
  const areaName = (id: string) => {
    if (id === "other") return t("console.otherArea");
    const a = areas?.find((x) => x.id === id);
    return a ? a.names[lang] ?? a.names.en : id;
  };

  async function askRules() {
    setProbe(null);
    try {
      await api.sget(`/v1/secure/console/queue?area=bengaluru&type=evidence`);
      setProbe({ ok: true });
    } catch (e) {
      setProbe(outcomeOf(e));
    }
  }

  if (!ready) return <div className="mx-auto max-w-[1400px] px-6 py-16"><Spinner /></div>;
  if (!user) {
    return (
      <div className="mx-auto max-w-[1400px] px-4 py-12 sm:px-6">
        <h1 className="text-[clamp(2.2rem,5vw,3.4rem)]">{t("console.title")}</h1>
        <p className="mt-4 max-w-prose text-[16.5px] text-ink-2">{t("console.signin")}</p>
        <button className="btn-primary mt-6" onClick={() => openAuth("signin")}>{t("nav.signin")}</button>
      </div>
    );
  }
  if (meError) return <div className="mx-auto max-w-[1400px] px-6 py-16"><ErrorNote>{t("common.error", { msg: (meError as Error).message })}</ErrorNote></div>;
  if (!me) return <div className="mx-auto max-w-[1400px] px-6 py-16"><Spinner label={t("common.loading")} /></div>;
  if (!official) {
    return (
      <div className="mx-auto max-w-[1400px] px-4 py-12 sm:px-6">
        <h1 className="text-[clamp(2.2rem,5vw,3.4rem)]">{t("console.title")}</h1>
        <p className="mt-4 max-w-prose text-[16.5px] text-ink-2">{t("console.noAccess")}</p>
        <button className="btn-quiet mt-6" onClick={askRules}>{t("console.tryRules")}</button>
        <div className="mt-4 max-w-2xl"><Denied o={probe} /></div>
        <Link className="link mt-6 inline-block" to="/about#rules">{t("defend.rulesLink")}</Link>
      </div>
    );
  }

  const items = queue.data ?? [];
  const canReview = me.user.role === "verifier" || me.user.role === "admin";
  const canRespond = me.user.role === "officer" || me.user.role === "admin";
  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6"><div className="max-w-[1100px]">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[clamp(2.2rem,5vw,3.4rem)]">{t("console.title")}</h1>
          <p className="mt-2 text-[15.5px] text-ink-2">
            {t("console.yourRole", { role: t(`me.role.${me.user.role}` as any), areas: me.user.jurisdictions.includes("*") ? t("console.allAreas") : me.user.jurisdictions.map(areaName).join(", ") })}, {me.user.pseudonym}
          </p>
        </div>
        <div className="w-full sm:w-64">
          <label className="label" htmlFor="console-area">{t("console.area")}</label>
          <select id="console-area" className="field" value={area} onChange={(e) => setArea(e.target.value)}>
            {allowedAreas.map((a) => <option key={a} value={a}>{areaName(a)}</option>)}
          </select>
        </div>
      </div>

      <Tabs.Root value={tab} onValueChange={setTab} className="mt-8">
        {/* four tabs outgrow narrow phones (and long labels in some languages): the row scrolls sideways; the
            hairline is an inset shadow so the active tab's bar can cover it without overflowing the scroller */}
        <Tabs.List ref={tabList} aria-label={t("console.title")} className="-mx-1 flex gap-x-3 overflow-x-auto shadow-[inset_0_-1px_0_rgb(var(--line))] [scrollbar-width:none] sm:gap-x-4 [&::-webkit-scrollbar]:hidden">
          {(["evidence", "dossiers", "waterlogging", "audit"] as const).map((k) => (
            <Tabs.Trigger key={k} value={k} className="shrink-0 whitespace-nowrap border-b-[3px] border-transparent px-1 pb-2.5 text-[15px] font-semibold text-ink-2 focus-visible:outline-offset-[-3px] data-[state=active]:border-memory data-[state=active]:text-ink sm:text-[16px]">
              {t(k === "waterlogging" ? "console.water" : (`console.${k}` as any))}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        {/* the queue holds the open tab's items only, so each list is built only while its tab is open */}
        <Tabs.Content value="evidence">
          {tab === "evidence" && (queue.isLoading ? <div className="py-6"><Spinner label={t("common.loading")} /></div> : queue.error ? <div className="py-6"><Denied o={outcomeOf(queue.error)} /></div> :
            items.length ? <ul className="divide-y divide-line">{items.map((e: Evidence) => <EvidenceItem key={e.evidenceId} e={e} canReview={canReview} onDone={refresh} />)}</ul>
              : <p className="muted py-6">{t("console.empty")}</p>)}
        </Tabs.Content>
        <Tabs.Content value="dossiers">
          {tab === "dossiers" && (queue.isLoading ? <div className="py-6"><Spinner label={t("common.loading")} /></div> : queue.error ? <div className="py-6"><Denied o={outcomeOf(queue.error)} /></div> :
            items.length ? <ul className="divide-y divide-line">{items.map((d: Dossier) => <DossierItem key={d.dossierId} d={d} canRespond={canRespond} onDone={refresh} />)}</ul>
              : <p className="muted py-6">{t("console.empty")}</p>)}
        </Tabs.Content>
        <Tabs.Content value="waterlogging">
          {tab === "waterlogging" && (queue.isLoading ? <div className="py-6"><Spinner label={t("common.loading")} /></div> : queue.error ? <div className="py-6"><Denied o={outcomeOf(queue.error)} /></div> :
            items.length ? <ul className="divide-y divide-line">{items.map((r: WaterReport) => <WaterItem key={r.reportId} r={r} canReview={canReview} onDone={refresh} />)}</ul>
              : <p className="muted py-6">{t("console.empty")}</p>)}
        </Tabs.Content>
        <Tabs.Content value="audit" className="pt-2">
          {audit.isLoading ? <div className="py-6"><Spinner label={t("common.loading")} /></div> : audit.error ? <div className="py-6"><Denied o={outcomeOf(audit.error)} /></div> :
            <AuditList entries={audit.data ?? []} />}
        </Tabs.Content>
      </Tabs.Root>
    </div></div>
  );
}
