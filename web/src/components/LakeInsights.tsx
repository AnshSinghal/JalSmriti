import { Bell, Camera, ExternalLink, FileSearch, FileSignature, Home, Newspaper, Share2, ShieldCheck, Users, Waves, Droplets } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { day, ha } from "../lib/format";
import { useT } from "../lib/i18n";
import { useLakeNews } from "../lib/queries";
import type { Cause, Evidence, Lake, LakeInsights, NewsArticle } from "../lib/types";

const BAR: Record<Cause["severity"], string> = { high: "bg-built", medium: "bg-lost", low: "bg-live" };
const BASIS: Record<Cause["key"], string> = {
  encroachment: "ins.basis.land", drying: "ins.basis.land", overgrown: "ins.basis.land",
  inflow: "ins.basis.series", sewage: "ins.basis.latest", holding: "ins.basis.all",
};

function CauseItem({ c }: { c: Cause }) {
  const { t, lang } = useT();
  const v = c.vars ?? {};
  const body: string[] = [];
  if (c.key === "encroachment") {
    body.push(t("ins.cause.encroachment.body", { ha: ha(v.ha), pct: v.pct ?? 0 }));
    if (v.since) body.push(t("ins.cause.encroachment.since", { year: v.since }));
  } else if (c.key === "drying") {
    body.push(t("ins.cause.drying.body", { ha: ha(v.ha) }));
  } else if (c.key === "overgrown") {
    body.push(t("ins.cause.overgrown.body", { ha: ha(v.ha) }));
    if (v.weedy) body.push(t("ins.cause.overgrown.weedy"));
  } else if (c.key === "inflow") {
    body.push(t("ins.cause.inflow.body", { pct: v.pct }));
    if (v.season && v.now != null && v.then != null) body.push(t("ins.cause.inflow.pair", { season: v.season, now: ha(v.now), then: ha(v.then) }));
  } else if (c.key === "sewage") {
    body.push(v.weedPct != null && v.weedPct >= 20
      ? t("ins.cause.sewage.weeds", { pct: Math.round(v.weedPct), date: day(v.date, lang) })
      : t("ins.cause.sewage.algae", { date: day(v.date, lang) }));
  } else {
    body.push(t("ins.cause.holding.body"));
  }
  return (
    <li className="relative pl-5">
      <span className={`absolute inset-y-1 left-0 w-1 rounded-full ${BAR[c.severity]}`} aria-hidden="true" />
      <h3 className="text-[1.25rem] leading-tight">{t(`ins.cause.${c.key}.title` as any)}</h3>
      <p className="mt-1.5 text-[16px] leading-snug">{body.join(" ")}</p>
      <p className="mt-1.5 text-[15px] leading-snug text-ink-2">{t(`ins.cause.${c.key}.why` as any)}</p>
      <p className="mt-1.5 text-[12.5px] text-ink-2"><span className="font-semibold">{t("ins.basis")}:</span> {t(BASIS[c.key] as any)}</p>
    </li>
  );
}

type Handlers = { photo: () => void; rti: () => void; watch: () => void; dossier: () => void };

const RESIDENT_ICON: Record<string, ReactNode> = {
  photo: <Camera size={17} />, rti: <FileSearch size={17} />, watch: <Bell size={17} />, dossier: <FileSignature size={17} />,
  home: <Home size={17} />, inflow: <Waves size={17} />, sewage: <Droplets size={17} />, group: <Users size={17} />,
};

function ResidentAction({ k, lake, on }: { k: string; lake: Lake; on: Handlers }) {
  const { t } = useT();
  const button = (() => {
    if (k === "photo") return <button className="btn-quiet tap" onClick={on.photo}><Camera size={15} /> {t("lake.addPhoto")}</button>;
    if (k === "rti") return <button className="btn-quiet tap" onClick={on.rti}><FileSearch size={15} /> {t("rti.button")}</button>;
    if (k === "watch") return <button className="btn-quiet tap" onClick={on.watch}><Bell size={15} /> {t("lake.watch")}</button>;
    if (k === "dossier") return <button className="btn-quiet tap" onClick={on.dossier}><FileSignature size={15} /> {t("lake.createDossier")}</button>;
    if (k === "home") return <Link className="btn-quiet tap" to={`/place?pick=1&lat=${lake.lat.toFixed(5)}&lon=${lake.lon.toFixed(5)}`}><Home size={15} /> {t("lact.home.button")}</Link>;
    return null;
  })();
  return (
    <li className="flex gap-3 py-3.5">
      <span className="mt-0.5 shrink-0 text-memory" aria-hidden="true">{RESIDENT_ICON[k] ?? <Share2 size={17} />}</span>
      <div className="min-w-0 flex-1">
        <p className="font-semibold leading-snug">{t(`lact.${k}.title` as any)}</p>
        <p className="mt-0.5 text-[15px] leading-snug text-ink-2">{t(`lact.${k}.body` as any)}</p>
        {button && <div className="mt-2">{button}</div>}
      </div>
    </li>
  );
}

/** Why the lake is in this state (likely causes from its satellite record), what would help, and what protecting it
 *  brings back. */
export function LakeWhy({ lake, on }: { lake: Lake; on: Handlers }) {
  const { t } = useT();
  const ins: LakeInsights | undefined = lake.insights;
  if (!ins || !ins.causes.length) return null;
  const auths = lake.authorities.filter((a) => a.kind !== "court");
  return (
    <section className="mt-14 grid gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] [&>*]:min-w-0" aria-labelledby="why-title">
      <div>
        <h2 id="why-title" className="text-[1.7rem]">{t("ins.title")}</h2>
        <p className="muted mt-1 max-w-prose text-[15px]">{t("ins.lede")}</p>
        <ol className="mt-6 space-y-7">{ins.causes.map((c) => <CauseItem key={c.key} c={c} />)}</ol>
        {ins.benefit && (
          <div className="mt-10 rounded-xl border border-memory/30 bg-memory/5 p-5">
            <h3 className="text-[1.25rem]">{t("ins.benefit.title")}</h3>
            <p className="mt-2 flex flex-wrap items-baseline gap-x-2">
              <span className="display num text-[2.4rem] leading-none text-memory">{ins.benefit.millionLitresLow.toLocaleString()}–{ins.benefit.millionLitresHigh.toLocaleString()}</span>
              <span className="text-[15px] text-ink-2">{t("ins.benefit.unit")}</span>
            </p>
            <p className="mt-2 text-[15.5px] leading-snug">{t("ins.benefit.body", { ha: ha(ins.benefit.lostHa), poolsLow: ins.benefit.poolsLow.toLocaleString(), poolsHigh: ins.benefit.poolsHigh.toLocaleString() })}</p>
            <p className="mt-2 text-[14.5px] leading-snug text-ink-2">{t("ins.benefit.more")}</p>
          </div>
        )}
      </div>
      <div>
        <h2 className="text-[1.7rem]">{t("ins.help.title")}</h2>
        <h3 className="mt-4 text-[1.1rem]">{t("ins.help.you")}</h3>
        <ul className="divide-y divide-line border-b border-line">{ins.actions.residents.map((k) => <ResidentAction key={k} k={k} lake={lake} on={on} />)}</ul>
        <h3 className="mt-8 text-[1.1rem]">{t("ins.help.ask")}</h3>
        {auths.length > 0 && <p className="muted mt-1 text-[14px]">{t("ins.help.askWho", { who: auths.slice(0, 2).map((a) => a.name).join(", ") })}</p>}
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-[15.5px] leading-snug marker:text-ink-2">
          {ins.actions.authorities.map((k) => <li key={k}>{t(`ask.${k}` as any)}</li>)}
        </ol>
      </div>
    </section>
  );
}

const TAG_TONE: Record<string, string> = {
  flood: "bg-memory/10 text-memory", encroachment: "bg-built/10 text-built", pollution: "bg-lost/15 text-ink", restoration: "bg-live/15 text-live",
};

function Headline({ a }: { a: NewsArticle }) {
  const { t, lang } = useT();
  return (
    <li className="py-3">
      <a href={a.url} target="_blank" rel="noreferrer noopener" className="group block">
        <span className="font-semibold leading-snug group-hover:text-memory">{a.title}<ExternalLink size={13} className="ml-1 inline opacity-60" aria-hidden="true" /></span>
        <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-ink-2">
          <span>{a.domain}</span>{a.date && <span>{day(a.date, lang)}</span>}
          {a.tags.map((g) => <span key={g} className={`tag ${TAG_TONE[g] ?? "bg-paper-2"}`}>{t(`news.tag.${g}` as any)}</span>)}
        </span>
      </a>
    </li>
  );
}

/** Recent news naming the lake, and how the lake is being protected here (photos, dossiers, RTI, watchers, ledger). */
export function LakeNewsAndRecord({ lake, evidence, dossiers, rtis, ledgerEntries }: {
  lake: Lake; evidence?: Evidence[]; dossiers?: { status: string }[]; rtis?: unknown[]; ledgerEntries?: number;
}) {
  const { t } = useT();
  const { data: news, isLoading } = useLakeNews(lake.lakeId);
  const verified = (evidence ?? []).filter((e) => e.status === "verified").length;
  const sent = (dossiers ?? []).filter((d) => !["drafting", "failed", "ready"].includes(d.status)).length;
  const stats: [string, number][] = [
    ["rec.photos", evidence?.length ?? 0], ["rec.verified", verified], ["rec.dossiers", dossiers?.length ?? 0],
    ["rec.sent", sent], ["rec.rti", rtis?.length ?? 0], ["rec.watchers", lake.watchers ?? 0], ["rec.ledger", ledgerEntries ?? 0],
  ];
  return (
    <section className="mt-14 grid gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] [&>*]:min-w-0">
      <div>
        <h2 className="flex items-center gap-2 text-[1.7rem]"><Newspaper size={22} aria-hidden="true" />{t("news.title")}</h2>
        <p className="muted mt-1 max-w-prose text-[14.5px]">{t("news.lede")}</p>
        {isLoading ? <p className="muted mt-4">{t("common.loading")}</p>
          : !news || news.status === "unavailable" ? <p className="muted mt-4">{t("news.busy")}</p>
          : news.status === "none" ? <p className="muted mt-4">{t("news.unnamed")}</p>
          : news.articles.length === 0 ? <p className="muted mt-4">{t("news.empty")}</p>
          : (
            <>
              {Object.keys(news.tags).length > 0 && (
                <p className="mt-3 text-[14.5px]">{t("news.about")}{" "}
                  {Object.entries(news.tags).sort((a, b) => b[1] - a[1]).map(([g, n]) => (
                    <span key={g} className={`tag mr-1.5 ${TAG_TONE[g] ?? "bg-paper-2"}`}>{t(`news.tag.${g}` as any)} {n}</span>
                  ))}
                </p>
              )}
              <ul className="mt-2 divide-y divide-line border-y border-line">{news.articles.slice(0, 8).map((a) => <Headline key={a.url} a={a} />)}</ul>
              {news.status === "stale" && <p className="muted mt-2 text-[13px]">{t("news.stale")}</p>}
            </>
          )}
      </div>
      <div>
        <h2 className="flex items-center gap-2 text-[1.7rem]"><ShieldCheck size={22} aria-hidden="true" />{t("rec.title")}</h2>
        <p className="muted mt-1 text-[14.5px]">{t("rec.lede")}</p>
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-2">
          {stats.map(([k, n]) => (
            <div key={k}>
              <dt className="text-[13.5px] text-ink-2">{t(k as any)}</dt>
              <dd className="display num text-[1.9rem] leading-none">{n}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 text-[14.5px] leading-snug text-ink-2">{t("rec.how")}</p>
      </div>
    </section>
  );
}
