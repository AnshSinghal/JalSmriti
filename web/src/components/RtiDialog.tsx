import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Download, Loader2, LogIn, Printer, X } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { day, ha } from "../lib/format";
import { useT } from "../lib/i18n";
import type { Lake, RtiRequest } from "../lib/types";
import { ErrorNote } from "./bits";

const ITEMS = ["survey", "encroach", "action", "permits", "works", "complaints"] as const;
type ItemKey = (typeof ITEMS)[number];
const CHANNELS = ["online", "post", "hand"] as const;
type Channel = (typeof CHANNELS)[number];

/** Today in the visitor's own time zone, as YYYY-MM-DD. */
export function todayIso(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

/** Put React nodes into a translated sentence's {placeholders}, so a name can be bold in any language's word order. */
export function fillNodes(template: string, parts: Record<string, ReactNode>): ReactNode {
  return template.split(/(\{\w+\})/g).map((seg, i) => {
    const k = /^\{(\w+)\}$/.exec(seg)?.[1];
    return <Fragment key={i}>{k && k in parts ? parts[k] : seg}</Fragment>;
  });
}

/** RTI requests recorded for a lake (or by a person, with the lake named), with the reply date and an overdue mark. */
export function RtiList({ items, showLake }: { items: RtiRequest[]; showLake?: boolean }) {
  const { t, lang } = useT();
  const today = todayIso();
  return (
    <ul className="mt-3 divide-y divide-line border-y border-line">
      {items.map((r) => {
        const overdue = !!r.dueBy && r.dueBy < today;
        const meta = [
          !showLake && r.by ? t("ev.by", { who: r.by }) : null,
          r.channel && (CHANNELS as readonly string[]).includes(r.channel) ? t(`rti.channel.${r.channel as Channel}` as const) : null,
          showLake && r.reference ? r.reference : null,
        ].filter(Boolean);
        return (
          <li key={r.rtiId} className="flex items-start justify-between gap-3 py-3">
            <div className="min-w-0">
              {showLake && <Link className="font-semibold hover:text-memory" to={`/lake/${r.lakeId}`}>{r.lakeName ?? r.lakeId}</Link>}
              <p className={showLake ? "text-[15px] leading-snug" : "text-[15.5px] leading-snug"}>
                {fillNodes(t("rti.list.item"), {
                  office: showLake ? r.office : <span className="font-semibold">{r.office}</span>,
                  date: day(r.filedOn, lang),
                  due: day(r.dueBy, lang),
                })}
              </p>
              {meta.length > 0 && <p className="muted mt-0.5 text-[13.5px]">{meta.join(" · ")}</p>}
            </div>
            {overdue && <span className="tag mt-0.5 shrink-0 bg-built/10 text-built">{t("rti.list.overdue")}</span>}
          </li>
        );
      })}
    </ul>
  );
}

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
/** "3. Text" -> ["3.", "Text"], so numbered requests can hang under their number. */
const numbered = (line: string) => /^(\d+\.)\s(.*)$/.exec(line);

/** A bare A4 page of the letter, in a serif the reader's system has, for printing or saving as PDF. */
function printableHtml(text: string, title: string, lang: string): string {
  const para = (l: string) => {
    const m = numbered(l);
    return m ? `<span class="l n"><span class="k">${esc(m[1])} </span>${esc(m[2])}</span>` : `<span class="l">${esc(l)}</span>`;
  };
  const body = text.split(/\n{2,}/).map((block) => `<p>${block.split("\n").map(para).join("")}</p>`).join("");
  return `<!doctype html><html lang="${esc(lang)}"><head><meta charset="utf-8"><title>${esc(title)}</title><style>
@page { size: A4; margin: 22mm 20mm; }
html, body { margin: 0; background: #fff; color: #000; }
body { font-family: "Noto Serif", Georgia, Cambria, "Times New Roman", "Noto Serif Devanagari", "Nirmala UI", serif; font-size: 12pt; line-height: 1.5; }
main { max-width: 170mm; margin: 0 auto; }
@media screen { main { padding: 18mm 0; } }
p { margin: 0 0 0.9em; white-space: pre-wrap; } .l { display: block; } .n { padding-left: 1.7em; text-indent: -1.7em; }
.k { display: inline-block; width: 1.7em; text-indent: 0; }
</style></head><body><main>${body}</main></body></html>`;
}

function printLetter(html: string) {
  const w = window.open("", "_blank");
  if (w) {
    w.document.open();
    w.document.write(html);
    w.document.close();
    w.focus();
    setTimeout(() => { try { w.print(); } catch { /* the page stays open to print by hand */ } }, 250);
    return;
  }
  // Pop-ups blocked: print from a hidden frame instead.
  const f = document.createElement("iframe");
  f.setAttribute("aria-hidden", "true");
  Object.assign(f.style, { position: "fixed", right: "0", bottom: "0", width: "0", height: "0", border: "0" });
  document.body.appendChild(f);
  const d = f.contentWindow?.document;
  if (!d) { f.remove(); return; }
  d.open();
  d.write(html);
  d.close();
  setTimeout(() => { f.contentWindow?.focus(); f.contentWindow?.print(); setTimeout(() => f.remove(), 2000); }, 250);
}

const linkify = (s: string): ReactNode =>
  s.split(/(rtionline\.gov\.in)/).map((seg, i) =>
    seg === "rtionline.gov.in" ? <a key={i} className="link" href="https://rtionline.gov.in" target="_blank" rel="noreferrer">{seg}</a> : seg);

/** A Right to Information application about one lake, written in the reader's language from the lake's own record,
 *  to copy, download or print; and, once filed, recorded on the lake's ledger with the date a reply is due. */
export default function RtiDialog({ lake, open, onClose }: { lake: Lake; open: boolean; onClose: () => void }) {
  const { t, lang } = useT();
  const { user, openAuth } = useAuth();
  const qc = useQueryClient();
  const boxRef = useRef<HTMLDivElement>(null);
  const np = lake.area?.country === "NP" || lake.admin?.countryCode?.toLowerCase() === "np";
  const offices = useMemo(() => lake.authorities.filter((a) => a.kind !== "court" && a.kind !== "grievance"), [lake.authorities]);
  const [officeId, setOfficeId] = useState(offices[0]?.id ?? "");
  const [officeText, setOfficeText] = useState("");
  const [chosen, setChosen] = useState<Record<ItemKey, boolean>>(() => Object.fromEntries(ITEMS.map((k) => [k, true])) as Record<ItemKey, boolean>);
  const [facts, setFacts] = useState(true);
  const [copied, setCopied] = useState(false);
  const [filedOn, setFiledOn] = useState(todayIso());
  const [reference, setReference] = useState("");
  const [channel, setChannel] = useState<Channel | "">("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [dueBy, setDueBy] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setFiledOn(todayIso());
    setReference("");
    setChannel("");
    setErr(null);
    setDueBy(null);
    setCopied(false);
  }, [open]);

  const office = (offices.length ? offices.find((a) => a.id === officeId)?.name : officeText.trim()) ?? "";
  const items = ITEMS.filter((k) => chosen[k]);
  const lostHa = lake.metrics.lostHa ?? 0;
  const builtHa = lake.metrics.builtHa ?? 0;
  const hasFacts = lostHa > 0 || builtHa > 0;

  // The letter, in the language the page is shown in; blank lines separate its paragraphs.
  const letter = [
    t(np ? "rti.toNp" : "rti.to", { office: office || "…" }),
    t(np ? "rti.subjectNp" : "rti.subject", { lake: lake.name, lat: lake.lat.toFixed(5), lon: lake.lon.toFixed(5) }),
    [t("rti.intro"), ...items.map((k, i) => `${i + 1}. ${t(`rti.item.${k}` as const, { lake: lake.name })}`)].join("\n"),
    ...(facts && hasFacts ? [t("rti.factsLine", { lostHa: ha(lostHa), builtHa: ha(builtHa) })] : []),
    t(np ? "rti.feeNp" : "rti.fee"),
    t(np ? "rti.timeNp" : "rti.time"),
    t("rti.sign"),
  ].join("\n\n");

  async function copy() {
    try {
      await navigator.clipboard.writeText(letter);
    } catch {
      // Older browsers: select a hidden copy inside the dialog (focus cannot leave an open dialog).
      const ta = document.createElement("textarea");
      ta.value = letter;
      ta.setAttribute("readonly", "");
      Object.assign(ta.style, { position: "fixed", top: "0", left: "0", opacity: "0" });
      (boxRef.current ?? document.body).appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch { /* nothing more to try */ }
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  }

  function download() {
    const name = lake.name.trim().replace(/[\\/:*?"<>|]+/g, "").replace(/\s+/g, "-") || lake.lakeId;
    const blob = new Blob(["﻿" + letter.replace(/\n/g, "\r\n")], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `rti-${name}.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api.spost<{ ok: boolean; rtiId: string; dueBy: string; ledgerSeq: number }>(`/v1/secure/lakes/${lake.lakeId}/rti`, {
        office, filedOn, reference: reference.trim() || undefined, channel: channel || undefined, items,
      });
      setDueBy(r.dueBy);
      qc.invalidateQueries({ queryKey: ["rti", lake.lakeId] });
      qc.invalidateQueries({ queryKey: ["ledger", lake.lakeId] });
      qc.invalidateQueries({ queryKey: ["activity"] });
    } catch (ex: any) {
      setErr(ex.decision?.rule ?? ex.message);
    } finally {
      setBusy(false);
    }
  }

  const btn = "btn-quiet px-3 py-2 text-[14.5px]";

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-[rgb(6_12_24/0.55)]" />
        <Dialog.Content ref={boxRef}
          className="fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(94vw,1040px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto overscroll-contain rounded-xl border border-line bg-paper p-4 shadow-2xl supports-[height:100dvh]:max-h-[92dvh] sm:p-7">
          <div className="flex items-start justify-between gap-3">
            <Dialog.Title className="display text-[1.8rem]">{t("rti.title")}</Dialog.Title>
            <Dialog.Close className="btn-ghost -mr-2 -mt-1 shrink-0" aria-label={t("common.close")}><X size={18} /></Dialog.Close>
          </div>
          <Dialog.Description className="muted mt-1 max-w-[70ch] text-[15px]">
            <span className="font-semibold text-ink">{lake.name}.</span> {np ? t("rti.ledeNp") : t("rti.ledeIn")}
          </Dialog.Description>

          <div className="mt-6 grid gap-x-9 gap-y-7 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:grid-rows-[auto_auto_1fr]">
            {/* who it goes to: a whole row, so long office names are not cut off */}
            <div className="min-w-0 lg:col-span-2 lg:row-start-1 lg:max-w-[42rem]">
              <label className="label" htmlFor="rti-office">{t("rti.office")}</label>
              {offices.length > 0 ? (
                <select id="rti-office" className="field" value={officeId} onChange={(e) => setOfficeId(e.target.value)}>
                  {offices.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              ) : (
                <input id="rti-office" className="field" value={officeText} maxLength={200} onChange={(e) => setOfficeText(e.target.value)} />
              )}
            </div>

            {/* what to ask for */}
            <div className="min-w-0 space-y-5 lg:col-start-1 lg:row-start-2">
              <fieldset>
                <legend className="label">{t("rti.items")}</legend>
                <ul className="divide-y divide-line border-y border-line">
                  {ITEMS.map((k) => (
                    <li key={k}>
                      <label className="flex cursor-pointer gap-3 py-2.5 text-[15px] leading-snug">
                        <input type="checkbox" className="mt-[3px] h-4 w-4 shrink-0 accent-[rgb(var(--memory))]" checked={chosen[k]}
                          onChange={(e) => setChosen((c) => ({ ...c, [k]: e.target.checked }))} />
                        <span className={chosen[k] ? "" : "text-ink-2"}>{t(`rti.item.${k}` as const, { lake: lake.name })}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              </fieldset>
              {hasFacts && (
                <label className="flex cursor-pointer gap-3 text-[15px] leading-snug">
                  <input type="checkbox" className="mt-[3px] h-4 w-4 shrink-0 accent-[rgb(var(--memory))]" checked={facts} onChange={(e) => setFacts(e.target.checked)} />
                  <span className="font-semibold">{t("rti.facts")}</span>
                </label>
              )}
            </div>

            {/* the letter */}
            <div className="min-w-0 lg:col-start-2 lg:row-span-2 lg:row-start-2">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <h3 id="rti-letter" className="text-[1.15rem]">{t("dossier.letter")}</h3>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={btn} onClick={copy} aria-live="polite">
                    {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}{copied ? t("rti.copied") : t("rti.copy")}
                  </button>
                  <button type="button" className={btn} onClick={download}><Download size={16} aria-hidden="true" />{t("rti.download")}</button>
                  <button type="button" className={btn} onClick={() => printLetter(printableHtml(letter, `${t("rti.title")} - ${lake.name}`, lang))}>
                    <Printer size={16} aria-hidden="true" />{t("rti.print")}
                  </button>
                </div>
              </div>
              <article aria-labelledby="rti-letter"
                className="mt-3 whitespace-pre-wrap break-words rounded-md border border-line bg-white px-5 py-6 text-[15px] leading-[1.6] text-[rgb(19_35_58)] shadow-[0_1px_0_rgb(var(--line))] dark:bg-paper-2 dark:text-ink sm:px-8 sm:py-8 sm:text-[15.5px]">
                {/* One <p> per paragraph and inline lines inside it, so selecting and copying the preview by hand
                    gives back the same text as the copy button; numbers hang in a fixed-width box. */}
                {letter.split(/\n{2,}/).map((block, i) => (
                  <p key={i} className="mt-[0.9em] first:mt-0">
                    {block.split("\n").map((line, j) => {
                      const m = numbered(line);
                      return m
                        ? <span key={j} className="block pl-[1.7em] -indent-[1.7em]"><span className="inline-block w-[1.7em] indent-0">{m[1]} </span>{m[2]}</span>
                        : <span key={j} className="block">{line}</span>;
                    })}
                  </p>
                ))}
              </article>
            </div>

            {/* filing it */}
            <div className="min-w-0 space-y-6 self-start lg:col-start-1 lg:row-start-3">
              <div>
                <h3 className="text-[1.15rem]">{t("dossier.how")}</h3>
                <p className="mt-1.5 text-[15px] leading-snug text-ink-2">{linkify(np ? t("rti.howNp") : t("rti.how"))}</p>
              </div>
              <section aria-labelledby="rti-filed" className="rounded-xl bg-paper-2 p-4 sm:p-5">
                <h3 id="rti-filed" className="text-[1.15rem]">{t("rti.filed.title")}</h3>
                {user ? (
                  <form onSubmit={save} className="mt-3">
                    <p className="text-[14.5px] leading-snug"><span className="text-ink-2">{t("dossier.to")}:</span> <span className="font-semibold">{office || "-"}</span></p>
                    <div className="mt-3 grid items-end gap-3 sm:grid-cols-2">
                      <div className="min-w-0">
                        <label className="label" htmlFor="rti-on">{t("rti.filed.on")}</label>
                        <input id="rti-on" type="date" className="field h-12" value={filedOn} min={todayIso(-365)} max={todayIso()} required
                          onChange={(e) => setFiledOn(e.target.value)} />
                      </div>
                      <div className="min-w-0">
                        <label className="label" htmlFor="rti-ref">{t("rti.filed.ref")}</label>
                        <input id="rti-ref" className="field h-12" value={reference} maxLength={120} onChange={(e) => setReference(e.target.value)} />
                      </div>
                    </div>
                    <fieldset className="mt-3">
                      <legend className="label">{t("rti.filed.channel")}</legend>
                      {/* real radio buttons, drawn as one segmented control */}
                      <div className="inline-flex max-w-full flex-wrap overflow-hidden rounded-md border border-line bg-paper">
                        {CHANNELS.map((c, i) => (
                          <label key={c}
                            className={`cursor-pointer px-3.5 py-2 text-[15px] font-semibold transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:-outline-offset-4 ${
                              i ? "border-l border-line" : ""} ${channel === c
                              ? "bg-ink text-paper has-[:focus-visible]:outline-paper"
                              : "text-ink hover:bg-paper-2 has-[:focus-visible]:outline-memory"}`}>
                            <input type="radio" name="rti-channel" value={c} checked={channel === c} onChange={() => setChannel(c)} className="sr-only" />
                            {t(`rti.channel.${c}` as const)}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                    {dueBy && <p role="status" className="mt-4 rounded-md bg-live/10 px-3 py-2 text-[15px] text-live">{t("rti.filed.done", { date: day(dueBy, lang) })}</p>}
                    {err && <div className="mt-4"><ErrorNote>{err}</ErrorNote></div>}
                    {!dueBy && (
                      <button className="btn-primary mt-4" disabled={busy || office.length < 3 || !filedOn}>
                        {busy && <Loader2 size={16} className="animate-spin" />}{t("rti.filed.save")}
                      </button>
                    )}
                  </form>
                ) : (
                  <button type="button" className="btn-quiet mt-3" onClick={() => openAuth("signin", t("auth.needed"))}>
                    <LogIn size={16} aria-hidden="true" />{t("nav.signin")}
                  </button>
                )}
              </section>
            </div>
          </div>

          <div className="mt-6 flex justify-end border-t border-line pt-4">
            <button type="button" className="btn-ghost" onClick={onClose}>{t("common.close")}</button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
