import { useQueryClient } from "@tanstack/react-query";
import { BellOff, Loader2, Mail } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorNote, Spinner } from "../components/bits";
import { fillNodes, RtiList } from "../components/RtiDialog";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dateTime, day } from "../lib/format";
import { useT } from "../lib/i18n";
import { useActivity, useAreas, useMe } from "../lib/queries";
import type { Follow, WaterReport } from "../lib/types";

function Section({ title, empty, children, count }: { title: string; empty: string; children: React.ReactNode; count: number }) {
  return (
    <section>
      <h2 className="text-[1.6rem]">{title}</h2>
      {count ? children : <p className="muted mt-2">{empty}</p>}
    </section>
  );
}

const TIER_TAG: Record<string, string> = { strong: "bg-built/10 text-built", some: "bg-lost/15 text-ink", little: "bg-memory/10 text-memory" };
const HEADS_UP: Record<string, ["me.follow.active" | "me.follow.pending" | "me.follow.unsubscribed", string]> = {
  active: ["me.follow.active", "bg-live/15 text-live"],
  "pending confirmation": ["me.follow.pending", "bg-lost/15"],
  unsubscribed: ["me.follow.unsubscribed", "bg-built/10 text-built"],
};

/** One followed place: its water memory, whether heads-ups reach the person, a test email to see one, and unfollow. */
function FollowRow({ f, headsUp }: { f: Follow; headsUp?: string }) {
  const { t, lang } = useT();
  const qc = useQueryClient();
  const [busy, setBusy] = useState<null | "test" | "stop">(null);
  const [test, setTest] = useState<{ subject: string; body: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const lat = Number(f.lat), lon = Number(f.lon);
  const href = `/place?lat=${lat.toFixed(5)}&lon=${lon.toFixed(5)}${f.label ? `&label=${encodeURIComponent(f.label)}` : ""}`;
  const status = headsUp ? HEADS_UP[headsUp] : undefined;

  async function run(kind: "test" | "stop") {
    setBusy(kind);
    setErr(null);
    try {
      if (kind === "test") {
        const r = await api.spost<{ ok: boolean; status: string; subject: string; body: string; local: boolean }>(`/v1/secure/follows/${f.gh7}/test`);
        setTest({ subject: r.subject, body: r.body });
      } else {
        await api.sdel(`/v1/secure/follows/${f.gh7}`);
      }
      await qc.invalidateQueries({ queryKey: ["activity"] });
    } catch (e: any) {
      setErr(e.decision?.rule ?? e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className="py-4">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <Link className="text-[17px] font-semibold leading-snug hover:text-memory" to={href}>
            {f.label ?? t("lake.coords", { lat: lat.toFixed(4), lon: lon.toFixed(4) })}
          </Link>
          {(TIER_TAG[f.tier ?? ""] || status) && (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {TIER_TAG[f.tier ?? ""] && <span className={`tag ${TIER_TAG[f.tier!]}`}>{t(`place.memory.${f.tier as "strong" | "some" | "little"}`)}</span>}
              {status && <span className={`tag ${status[1]}`}>{t(status[0])}</span>}
            </div>
          )}
          {f.lastAlertFor && <p className="muted mt-1 text-[13.5px]">{t("me.follow.lastAlert", { date: day(f.lastAlertFor, lang) })}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-quiet px-3 py-2 text-[14.5px]" onClick={() => run("test")} disabled={!!busy}>
            {busy === "test" ? <Loader2 size={16} className="animate-spin" /> : <Mail size={16} aria-hidden="true" />}{t("me.follow.test")}
          </button>
          <button className="btn-ghost px-3 py-2 text-[14.5px]" onClick={() => run("stop")} disabled={!!busy}>
            {busy === "stop" ? <Loader2 size={16} className="animate-spin" /> : <BellOff size={16} aria-hidden="true" />}{t("me.unfollow")}
          </button>
        </div>
      </div>
      {test && (
        <div className="mt-3 max-w-3xl">
          <p role="status" className="text-[15px] text-live">{fillNodes(t("me.follow.testSent"), { subject: <span className="font-semibold">{test.subject}</span> })}</p>
          <div className="label mt-3" id={`mail-${f.gh7}`}>{t("me.follow.preview")}</div>
          <pre tabIndex={0} aria-labelledby={`mail-${f.gh7}`}
            className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-paper-2 p-3 font-sans text-[14px] leading-relaxed sm:p-4">
            {test.body}
          </pre>
        </div>
      )}
      {err && <div className="mt-3"><ErrorNote>{err}</ErrorNote></div>}
    </li>
  );
}

const WATER_TAG: Record<string, string> = {
  verified: "bg-live/15 text-live", live: "bg-paper-2 text-ink", hidden: "bg-lost/15 text-ink", uploading: "bg-paper-3 text-ink-2",
  rejected: "bg-built/10 text-built", blocked: "bg-built/10 text-built", "no-location": "bg-built/10 text-built", unreadable: "bg-built/10 text-built",
};

function WaterCard({ w }: { w: WaterReport }) {
  const { t, lang } = useT();
  const statusKey = `wl.status.${w.status}` as const;
  const status = t(statusKey as any);
  const depth = w.depth ?? w.ai?.depth ?? "none";
  const depthText = t(`wl.depth.${depth}` as any);
  return (
    <li className="overflow-hidden rounded-lg border border-line">
      <Link to="/waterlogging" className="block hover:text-memory">
        <div className="aspect-[4/3] bg-paper-3">{w.thumbUrl && <img src={w.thumbUrl} alt={w.ai?.summary ?? ""} className="h-full w-full object-cover" loading="lazy" />}</div>
        <div className="space-y-1 p-3 text-[14px]">
          <span className={`tag ${WATER_TAG[w.status] ?? "bg-paper-2 text-ink"}`}>{status === statusKey ? w.status : status}</span>
          <div className="font-semibold">{day(w.seenAt ?? w.createdAt, lang)}</div>
          <div className="muted">{depthText.startsWith("wl.depth.") ? t("wl.depth.none") : depthText}</div>
        </div>
      </Link>
    </li>
  );
}

export default function Account() {
  const { t, lang } = useT();
  const { user, ready, openAuth } = useAuth();
  const { data: me } = useMe(!!user);
  const { data: areas } = useAreas();
  const { data: act, isLoading, error } = useActivity(!!user);

  if (!ready) return <div className="mx-auto max-w-[1400px] px-6 py-16"><Spinner /></div>;
  if (!user) {
    return (
      <div className="mx-auto max-w-[1400px] px-4 py-12 sm:px-6">
        <h1 className="text-[clamp(2.2rem,5vw,3.4rem)]">{t("me.title")}</h1>
        <p className="mt-4 max-w-prose text-[16.5px] text-ink-2">{t("me.signin")}</p>
        <button className="btn-primary mt-6" onClick={() => openAuth("signin")}>{t("nav.signin")}</button>
      </div>
    );
  }
  const areaName = (id: string) => { const a = areas?.find((x) => x.id === id); return a ? a.names[lang] ?? a.names.en : id; };
  const role = me?.user.role ?? user.role;
  const follows = act?.follows ?? [];
  const water = act?.waterReports ?? [];
  const rti = act?.rti ?? [];
  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6"><div className="max-w-[1100px]">
      <h1 className="text-[clamp(2.2rem,5vw,3.4rem)]">{t("me.title")}</h1>
      <div className="mt-6 grid gap-x-10 gap-y-4 rounded-xl bg-paper-2 p-5 text-[15.5px] sm:grid-cols-3">
        <div><div className="label">{t("me.role")}</div><div className="font-semibold">{t(`me.role.${role}` as any)}</div></div>
        <div><div className="label">{t("me.email")}</div><div className="break-all">{me?.user.email ?? user.email ?? "-"}</div></div>
        <div><div className="label">{t("me.publicName")}</div><div className="font-semibold">{me?.user.pseudonym ?? "-"}</div></div>
        {role !== "citizen" && me && (
          <div className="sm:col-span-3">
            <div className="label">{t("me.jurisdictions")}</div>
            <div>{me.user.jurisdictions.includes("*") ? t("me.allAreas") : me.user.jurisdictions.map(areaName).join(", ")}</div>
            <Link className="btn-quiet mt-3" to="/console">{t("me.openConsole")}</Link>
          </div>
        )}
      </div>

      {isLoading && <div className="mt-10"><Spinner label={t("common.loading")} /></div>}
      {error && <div className="mt-10"><ErrorNote>{t("common.error", { msg: (error as Error).message })}</ErrorNote></div>}
      {act && (
        <div className="mt-12 space-y-12">
          <Section title={t("me.follows")} empty={t("me.empty")} count={follows.length}>
            <ul className="mt-3 divide-y divide-line border-y border-line">
              {follows.map((f) => <FollowRow key={f.gh7} f={f} headsUp={act.headsUp?.status} />)}
            </ul>
          </Section>
          <Section title={t("me.watches")} empty={t("me.empty")} count={act.watches.length}>
            <ul className="mt-3 divide-y divide-line border-y border-line">
              {act.watches.map((w) => (
                <li key={w.lakeId} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <Link className="font-semibold hover:text-memory" to={`/lake/${w.lakeId}`}>{w.lakeName ?? w.lakeId}</Link>
                  <span className={`tag ${w.status === "active" ? "bg-live/15 text-live" : "bg-lost/15"}`}>{w.status === "active" ? t("me.watch.active") : t("me.watch.pending")}</span>
                </li>
              ))}
            </ul>
          </Section>
          <Section title={t("me.dossiers")} empty={t("me.empty")} count={act.dossiers.length}>
            <ul className="mt-3 divide-y divide-line border-y border-line">
              {act.dossiers.map((d) => (
                <li key={d.dossierId}>
                  <Link to={`/dossier/${d.dossierId}`} className="flex flex-wrap items-center justify-between gap-3 py-3 hover:text-memory">
                    <span className="min-w-0"><span className="block font-semibold">{d.lakeName ?? d.lakeId}</span>
                      <span className="muted text-[13.5px]">{d.recipient?.name}, {dateTime(d.createdAt, lang)}</span></span>
                    <span className="tag shrink-0 bg-paper-2">{t(`dossier.status.${d.status}` as any)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Section>
          <Section title={t("me.rti")} empty={t("me.empty")} count={rti.length}>
            <RtiList items={rti} showLake />
          </Section>
          <Section title={t("me.evidence")} empty={t("me.empty")} count={act.evidence.length}>
            <ul className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4 [&>*]:min-w-0">
              {act.evidence.map((e) => (
                <li key={e.evidenceId} className="overflow-hidden rounded-lg border border-line">
                  <Link to={`/lake/${e.lakeId}`} className="block">
                    <div className="aspect-[4/3] bg-paper-3">{e.thumbUrl && <img src={e.thumbUrl} alt="" className="h-full w-full object-cover" loading="lazy" />}</div>
                    <div className="p-3 text-[14px]">
                      <div className="truncate font-semibold">{e.lakeName ?? e.lakeId}</div>
                      <div className="muted">{t(`ev.status.${e.status}` as any)}, {dateTime(e.createdAt, lang)}</div>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </Section>
          <Section title={t("me.water")} empty={t("me.empty")} count={water.length}>
            <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4 [&>*]:min-w-0">
              {water.map((w) => <WaterCard key={w.reportId} w={w} />)}
            </ul>
          </Section>
        </div>
      )}
    </div></div>
  );
}
