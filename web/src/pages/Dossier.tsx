import * as Tabs from "@radix-ui/react-tabs";
import { useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorNote, Spinner } from "../components/bits";
import ShareButtons from "../components/ShareButtons";
import Timeline from "../components/Timeline";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dateTime, ha, pct } from "../lib/format";
import { useT } from "../lib/i18n";
import { useDossier, useMe } from "../lib/queries";
import type { Dossier } from "../lib/types";

function Letter({ subject, body, asks, dir }: { subject?: string; body?: string; asks?: string[]; dir?: "rtl" | "ltr" }) {
  const { t } = useT();
  return (
    <article dir={dir} className="rounded-lg border border-line bg-paper px-5 py-6 shadow-[0_1px_0_rgb(var(--line))] sm:px-8 sm:py-8">
      {subject && <h3 className="text-[1.25rem] leading-snug">{subject}</h3>}
      <div className="mt-4 max-w-[68ch] text-[16px] leading-[1.65]">
        {(body ?? "").split(/\n{2,}/).map((para, i) => <p key={i} className="mt-3 whitespace-pre-line first:mt-0">{para}</p>)}
      </div>
      {asks && asks.length > 0 && (
        <>
          <h4 className="mt-6 text-[15px] font-bold">{t("dossier.asks")}</h4>
          <ol className="mt-2 list-decimal space-y-1.5 pl-6 text-[16px] leading-snug">{asks.map((a, i) => <li key={i}>{a}</li>)}</ol>
        </>
      )}
    </article>
  );
}

function Facts({ d }: { d: Dossier }) {
  const { t } = useT();
  const f = d.facts ?? {};
  const rows: [string, string][] = [];
  if (f.grade) rows.push([t("lake.grade"), `${f.grade} (${f.score ?? "-"}/100)`]);
  if (f.historicHa != null) rows.push([t("lake.historic"), `${ha(f.historicHa)} ${t("common.ha")}`]);
  if (f.lostHa != null) rows.push([t("lake.lost"), `${ha(f.lostHa)} ${t("common.ha")}${f.lostPct != null ? `, ${pct(f.lostPct)}` : ""}`]);
  if (f.builtHa != null) rows.push([t("lake.built"), `${ha(f.builtHa)} ${t("common.ha")}${f.builtPct != null ? `, ${pct(f.builtPct)}` : ""}`]);
  if (f.retentionPct != null) rows.push([t("lake.retention"), pct(f.retentionPct)]);
  if (f.weedPct != null) rows.push([t("lake.weeds"), pct(f.weedPct)]);
  if (f.storageHighML) rows.push([t("lake.storage"), `${ha(f.storageLowML, 0)}-${ha(f.storageHighML, 0)} ML`]);
  if (f.evidenceCount != null) rows.push([t("lake.evidence"), t("dossier.evidence", { n: f.evidenceCount, v: f.verifiedCount ?? 0 })]);
  if (!rows.length) return null;
  return (
    <div>
      <h3>{t("dossier.facts")}</h3>
      <dl className="mt-2 divide-y divide-line text-[15px]">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 py-2">
            <dt className="text-ink-2">{k}</dt>
            <dd className="num shrink-0 text-right">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function SubmitForm({ d }: { d: Dossier }) {
  const { t } = useT();
  const qc = useQueryClient();
  const [portal, setPortal] = useState("");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api.spost(`/v1/secure/dossiers/${d.dossierId}/submitted`, { portal, reference });
      await qc.invalidateQueries({ queryKey: ["dossier", d.dossierId] });
    } catch (ex: any) {
      setErr(ex.decision?.rule ?? ex.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={go} className="rounded-xl bg-paper-2 p-5">
      <h3>{t("dossier.submitTitle")}</h3>
      <label className="label mt-4" htmlFor="ds-portal">{t("dossier.portal")}</label>
      <input id="ds-portal" className="field" value={portal} maxLength={120} onChange={(e) => setPortal(e.target.value)}
        placeholder={t("dossier.portalPlaceholder")} required />
      <label className="label mt-3" htmlFor="ds-ref">{t("dossier.reference")}</label>
      <input id="ds-ref" className="field" value={reference} maxLength={120} onChange={(e) => setReference(e.target.value)} />
      {err && <div className="mt-3"><ErrorNote>{err}</ErrorNote></div>}
      <button className="btn-primary mt-4" disabled={busy || portal.trim().length < 2}>
        {busy && <Loader2 size={16} className="animate-spin" />}{t("dossier.markSubmitted")}
      </button>
    </form>
  );
}

export default function DossierPage() {
  const { id } = useParams();
  const { t, lang } = useT();
  const { user, openAuth } = useAuth();
  const { data: d, isLoading, error } = useDossier(id);
  const { data: me } = useMe(!!user);

  if (isLoading) return <div className="mx-auto max-w-[1400px] px-6 py-16"><Spinner label={t("common.loading")} /></div>;
  if (error || !d) return <div className="mx-auto max-w-[1400px] px-6 py-16"><ErrorNote>{t("dossier.notFound")}</ErrorNote></div>;

  const signed = !!d.pdfUrl && !["drafting", "failed"].includes(d.status);
  const tr = d.translation && !d.translation.error && d.translation.body ? d.translation : null;
  const isCreator = !!me && me.user.pseudonym === d.creator;
  const rtl = d.language === "ur";

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6">
      <p className="muted text-[15px]">{t("dossier.title")}</p>
      <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
        <h1 className="max-w-[24ch] text-[clamp(2.1rem,4.6vw,3.4rem)]">
          <Link to={`/lake/${d.lakeId}`} className="hover:text-memory">{t("dossier.for", { lake: d.lakeName ?? d.lakeId })}</Link>
        </h1>
        <span className="tag bg-paper-2 px-2.5 py-1 text-[14px]">{t(`dossier.status.${d.status}` as any)}</span>
      </div>
      <p className="mt-2 text-[15.5px] text-ink-2">
        {d.recipient?.name && <>{t("dossier.to")} {d.recipient.name}, </>}{t("dossier.by", { who: d.creator ?? "-" })}, {dateTime(d.createdAt, lang)}
      </p>

      {signed && (
        <div className="mt-5 flex flex-wrap gap-2">
          <a className="btn-primary" href={d.pdfUrl} target="_blank" rel="noreferrer" download><Download size={17} /> {t("dossier.download")}</a>
          <Link className="btn-memory" to={`/verify/${d.dossierId}`}><ShieldCheck size={17} /> {t("dossier.verify")}</Link>
          <ShareButtons text={t("share.dossier", { lake: d.lakeName ?? d.lakeId })} path={`/verify/${d.dossierId}`} />
        </div>
      )}

      {d.status === "drafting" && (
        <div className="mt-8 flex max-w-2xl items-start gap-4 rounded-xl border border-line p-5">
          <Loader2 size={22} className="mt-0.5 shrink-0 animate-spin text-memory" />
          <div>
            <p className="font-semibold">{t("ds.drafting")}</p>
            <p className="muted mt-1 text-[15px]">{t("dossier.draftingNote")}</p>
          </div>
        </div>
      )}
      {d.status === "failed" && <div className="mt-8 max-w-2xl"><ErrorNote>{t("ds.failed", { msg: d.error ?? "-" })}</ErrorNote></div>}

      <div className="mt-10 grid gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,4fr)] [&>*]:min-w-0">
        <div className="min-w-0">
          {d.letter && (
            <>
              <h2 className="text-[1.7rem]">{t("dossier.letter")}</h2>
              {tr ? (
                <Tabs.Root defaultValue={d.language === lang ? "tr" : "en"} className="mt-4">
                  <Tabs.List aria-label={t("dossier.letter")} className="mb-4 inline-flex gap-1 rounded-lg border border-line p-1">
                    <Tabs.Trigger value="en" className="rounded-md px-3 py-1.5 text-[14.5px] font-semibold text-ink-2 data-[state=active]:bg-ink data-[state=active]:text-paper">English</Tabs.Trigger>
                    <Tabs.Trigger value="tr" className="rounded-md px-3 py-1.5 text-[14.5px] font-semibold text-ink-2 data-[state=active]:bg-ink data-[state=active]:text-paper">{tr.languageName ?? d.language}</Tabs.Trigger>
                  </Tabs.List>
                  <Tabs.Content value="en"><Letter {...d.letter} /></Tabs.Content>
                  <Tabs.Content value="tr">
                    <Letter subject={tr.subject} body={tr.body} asks={tr.asks} dir={rtl ? "rtl" : "ltr"} />
                    {tr.engine && <p className="muted mt-2 text-[13.5px]">{t("dossier.machine", { engine: tr.engine })}</p>}
                  </Tabs.Content>
                </Tabs.Root>
              ) : (
                <div className="mt-4">
                  <Letter {...d.letter} />
                  {d.translation?.error && <p className="muted mt-2 text-[13.5px]">{t("dossier.translationFailed")}</p>}
                </div>
              )}
              {d.letter.model && <p className="muted mt-2 text-[13.5px]">{t("dossier.model", { model: d.letter.model })}</p>}
            </>
          )}
          {signed && (
            <div className="mt-10">
              <h3>{t("dossier.nextSteps")}</h3>
              <ol className="mt-3 list-decimal space-y-2 pl-6 text-[16px]">
                <li>{t("dossier.next1")}</li>
                <li>{t("dossier.next2")}</li>
                <li>{t("dossier.next3")} <Link className="link" to={`/lake/${d.lakeId}`}>{d.lakeName}</Link></li>
              </ol>
            </div>
          )}
        </div>

        <aside className="min-w-0 space-y-9">
          {d.recipient && (
            <div>
              <h3>{t("dossier.to")}</h3>
              <p className="mt-1.5 text-[16px] font-semibold leading-snug">
                {d.recipient.url ? <a className="link" href={d.recipient.url} target="_blank" rel="noreferrer">{d.recipient.name}</a> : d.recipient.name}
              </p>
              {d.recipient.how && <p className="mt-1.5 text-[15px] text-ink-2"><span className="font-semibold text-ink">{t("dossier.how")}:</span> {d.recipient.how}</p>}
            </div>
          )}
          {d.status === "ready" && (
            isCreator ? <SubmitForm d={d} /> : (
              <p className="muted text-[14.5px]">
                {t("dossier.onlyCreator")}{" "}
                {!user && <button className="link text-ink" onClick={() => openAuth("signin", t("auth.needed"))}>{t("nav.signin")}</button>}
              </p>
            )
          )}
          {d.submission && <p className="rounded-md bg-live/10 px-3 py-2 text-[15px] text-live">{t("console.submittedRef", { portal: d.submission.portal || "-", ref: d.submission.reference || "-" })}</p>}
          <div>
            <h3>{t("dossier.timeline")}</h3>
            <div className="mt-3"><Timeline entries={d.timeline ?? []} /></div>
          </div>
          {signed && (
            <div>
              <h3>{t("dossier.fingerprints")}</h3>
              <p className="muted mt-1 text-[14px]">{t("dossier.signed")}</p>
              <dl className="mt-3 space-y-2 text-[13px]">
                <div><dt className="font-semibold">{t("dossier.contentHash")} (SHA-256)</dt><dd className="num break-all text-ink-2">{d.payloadSha256}</dd></div>
                <div><dt className="font-semibold">{t("dossier.pdfHash")} (SHA-256)</dt><dd className="num break-all text-ink-2">{d.pdfSha256}</dd></div>
              </dl>
            </div>
          )}
          <Facts d={d} />
        </aside>
      </div>
    </div>
  );
}
