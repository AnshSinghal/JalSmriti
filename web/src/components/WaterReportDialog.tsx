import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Camera, Check, Loader2, LocateFixed, MapPin, MapPinOff, ShieldCheck, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, uploadToS3 } from "../lib/api";
import { useT } from "../lib/i18n";
import type { WaterReport } from "../lib/types";
import { ErrorNote } from "./bits";

/* ------------------------------------------------------------------------------------------ shared bits
   Depth colours, tags and pictograms are used by the dialog, the standing-water page and the review console. */

export const DEPTHS = ["ankle", "knee", "waist", "vehicle"] as const;
export type Depth = (typeof DEPTHS)[number];
export const isDepth = (d: unknown): d is Depth => typeof d === "string" && (DEPTHS as readonly string[]).includes(d);

/** Background classes for the depth colours: the same tokens the map dots are painted with (depthColor). */
export const DEPTH_BG: Record<Depth | "none", string> = {
  ankle: "bg-memory", knee: "bg-lost", waist: "bg-built", vehicle: "bg-[#8f1d1a]", none: "bg-ink-2",
};
const DEPTH_VAR: Record<Depth | "none", string | null> = { ankle: "--memory", knee: "--lost", waist: "--built", vehicle: null, none: "--ink-2" };

/** The depth colour as a CSS colour MapLibre can paint (it cannot read CSS variables): the theme token, read now. */
export function depthColor(depth?: string | null): string {
  const v = DEPTH_VAR[isDepth(depth) ? depth : "none"];
  if (!v) return "#8f1d1a";
  const rgb = getComputedStyle(document.documentElement).getPropertyValue(v).trim().split(/\s+/).join(", ");
  return rgb ? `rgb(${rgb})` : "#7c8a9c";
}

type T = ReturnType<typeof useT>["t"];

/** "12 min ago", "5 h ago", "3 days ago" (hours up to two days, so the plural is always right). */
export function agoText(iso: string | undefined, t: T, now = Date.now()): string {
  const at = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(at)) return "-";
  const mins = Math.max(0, Math.floor((now - at) / 60_000));
  if (mins < 60) return t("wl.ago.min", { n: Math.max(1, mins) });
  const h = Math.floor(mins / 60);
  return h < 48 ? t("wl.ago.h", { n: h }) : t("wl.ago.d", { n: Math.floor(h / 24) });
}

export function DepthTag({ depth }: { depth?: string | null }) {
  const { t } = useT();
  const d = isDepth(depth) ? depth : "none";
  return (
    <span className="tag gap-1.5 bg-paper-2 text-ink">
      <i aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${DEPTH_BG[d]}`} />
      {t(`wl.depth.${d}` as any)}
    </span>
  );
}

export function StatusTag({ status }: { status: string }) {
  const { t } = useT();
  const tone = status === "verified" ? "bg-live/15 text-live" : status === "rejected" ? "bg-built/10 text-built"
    : status === "hidden" ? "bg-lost/15 text-ink" : "text-ink-2 ring-1 ring-inset ring-line";
  return (
    <span className={`tag gap-1 ${tone}`}>
      {status === "verified" && <Check size={12} strokeWidth={3} aria-hidden="true" />}
      {t(`wl.status.${status}` as any)}
    </span>
  );
}

/** Where the water stands on a person (ankle, knee, waist) or a car (above the wheels): one colour, decorative. */
const WATER_TOP: Record<Depth, number> = { ankle: 40, knee: 34, waist: 26, vehicle: 27 };
const wave = (y: number) => `M0 ${y}q3 -2.5 6 0t6 0t6 0t6 0t6 0t6 0t6 0t6 0`;

export function DepthIcon({ depth, className }: { depth: Depth; className?: string }) {
  const y = WATER_TOP[depth];
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden="true" focusable="false">
      {depth === "vehicle" ? (
        <g fill="none" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round">
          <path d="M9.5 33H5v-6.5l5-2 5-8h18l5 8 5 2V33h-4.5M18.5 33h11" />
          <circle cx="14" cy="33" r="4.5" />
          <circle cx="34" cy="33" r="4.5" />
        </g>
      ) : (
        <g fill="none" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round">
          <circle cx="24" cy="7.5" r="3.6" fill="currentColor" stroke="none" />
          <path d="M24 14v13M24 27l-6 17M24 27l6 17M16 25l8-9 8 9" />
        </g>
      )}
      <path d={`${wave(y)}V48H0z`} fill="currentColor" fillOpacity="0.22" />
      <path d={wave(y)} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/* ------------------------------------------------------------------------------------------ the dialog */

const MAX_BYTES = 12 * 1024 * 1024;
const TYPES = ["image/jpeg", "image/png", "image/webp"];
const POLL_MS = 2500;
const POLL_TRIES = 30;

type Geo = { state: "idle" | "locating" | "located" | "failed"; lat?: number; lon?: number; acc?: number };
type Outcome =
  | { kind: "live"; report: WaterReport }
  | { kind: "hidden"; reason?: string }
  | { kind: "slow" | "noLocation" | "blocked" }
  | { kind: "error"; msg: string };
type Upload = { reportId: string; upload: { url: string; fields: Record<string, string> }; maxBytes: number };

export default function WaterReportDialog({ open, onClose, start, onSee }: {
  open: boolean;
  onClose: () => void;
  start?: { lat: number; lon: number } | null;   // a place the person came from (?report=1&lat=..&lon=..)
  onSee?: (r: WaterReport) => void;               // "See it on the map": the page closes the dialog and selects it
}) {
  const { t } = useT();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [geo, setGeo] = useState<Geo>({ state: "idle" });
  const [depth, setDepth] = useState<Depth | null>(null);
  const [note, setNote] = useState("");
  const [phase, setPhase] = useState<"idle" | "sending" | "checking">("idle");
  const [out, setOut] = useState<Outcome | null>(null);
  const session = useRef(0);               // bumps each time the dialog opens or closes: late answers are dropped
  const doneRef = useRef<HTMLButtonElement>(null);
  const preview = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  useEffect(() => {
    session.current++;
    setFile(null); setGeo({ state: "idle" }); setDepth(null); setNote(""); setPhase("idle"); setOut(null);
  }, [open]);

  const busy = phase !== "idle";
  const sent = out?.kind === "live" || out?.kind === "hidden" || out?.kind === "slow";
  const tooBig = !!file && file.size > MAX_BYTES;
  const where = geo.state === "located" ? { lat: geo.lat!, lon: geo.lon!, accuracyM: geo.acc }
    : start ? { lat: start.lat, lon: start.lon } : null;
  useEffect(() => { if (sent) doneRef.current?.focus(); }, [sent]);

  function pick(f: File) {                 // a cancelled picker sends no file: the chosen photo stays
    setFile(f);
    if (out) setOut(null);                 // a new photo clears an earlier refusal
  }

  function locate() {
    if (!("geolocation" in navigator)) { setGeo({ state: "failed" }); return; }
    const s = session.current;
    setGeo((g) => ({ ...g, state: "locating" }));
    navigator.geolocation.getCurrentPosition(
      (p) => { if (session.current === s) setGeo({ state: "located", lat: p.coords.latitude, lon: p.coords.longitude, acc: Math.max(1, Math.round(p.coords.accuracy)) }); },
      () => { if (session.current === s) setGeo((g) => (g.lat != null ? { ...g, state: "located" } : { state: "failed" })); },
      { enableHighAccuracy: true, timeout: 15000 },
    );
  }

  async function send() {
    if (!file || busy || tooBig) return;
    const s = session.current;
    const alive = () => session.current === s;
    setOut(null);
    setPhase("sending");
    try {
      const contentType = TYPES.includes(file.type) ? file.type : "image/jpeg";
      const r = await api.spost<Upload>("/v1/secure/waterlogging/upload", {
        contentType, size: file.size, ...(where ?? {}), depth: depth ?? undefined, note: note.trim() || undefined,
      });
      await uploadToS3(r.upload, file);      // finishes even if the dialog was closed meanwhile
      if (!alive()) return;
      setPhase("checking");
      for (let i = 0; i < POLL_TRIES; i++) {
        await new Promise((res) => setTimeout(res, POLL_MS));
        if (!alive()) return;
        const rep = await api.sget<WaterReport>(`/v1/secure/waterlogging/${r.reportId}`).catch(() => null);
        if (!alive()) return;
        if (!rep?.status || rep.status === "uploading") continue;
        setPhase("idle");
        if (rep.status === "live" || rep.status === "verified") setOut({ kind: "live", report: rep });
        else if (rep.status === "hidden") setOut({ kind: "hidden", reason: rep.hiddenReason });
        else if (rep.status === "no-location") setOut({ kind: "noLocation" });
        else setOut({ kind: "blocked" });    // blocked, unreadable
        if (rep.status === "live" || rep.status === "verified" || rep.status === "hidden") qc.invalidateQueries({ queryKey: ["water"] });
        return;
      }
      setPhase("idle");
      setOut({ kind: "slow" });
      qc.invalidateQueries({ queryKey: ["water"] });
    } catch (e: any) {
      if (!alive()) return;
      setPhase("idle");
      setOut({ kind: "error", msg: e?.decision?.rule ?? e?.message ?? String(e) });
    }
  }

  const coords = (lat: number, lon: number) => t("lake.coords", { lat: lat.toFixed(4), lon: lon.toFixed(4) });

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-[rgb(6_12_24/0.55)]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(94vw,540px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto overscroll-contain rounded-xl border border-line bg-paper p-5 shadow-2xl sm:p-6">
          <div className="flex items-start justify-between gap-4">
            <Dialog.Title className="display text-[1.8rem]">{t("wl.dlg.title")}</Dialog.Title>
            <Dialog.Close className="btn-ghost -mr-2 -mt-1" aria-label={t("common.close")}><X size={18} /></Dialog.Close>
          </div>
          <Dialog.Description className={sent ? "sr-only" : "muted mt-1 text-[15px] leading-snug"}>{t("wl.dlg.photoHint")}</Dialog.Description>

          {sent ? (
            <div className="mt-4" role="status">
              <div className="flex gap-4">
                {preview && <img src={preview} alt="" className="h-20 w-[6.5rem] shrink-0 rounded-md object-cover" />}
                <div className="min-w-0">
                  {out?.kind === "live"
                    ? <p className="flex items-start gap-2 text-[16.5px] font-semibold leading-snug text-live"><Check size={19} className="mt-0.5 shrink-0" aria-hidden="true" />{t("wl.dlg.done")}</p>
                    : <p className="text-[15.5px] leading-snug">{out?.kind === "hidden" ? t(out.reason === "text" ? "wl.dlg.hiddenText" : "wl.dlg.hidden") : t("wl.dlg.slow")}</p>}
                  <div className="mt-2.5"><DepthTag depth={depth} /></div>
                </div>
              </div>
              <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                {out?.kind === "live" && onSee ? (
                  <>
                    <button type="button" className="btn-ghost" onClick={onClose}>{t("common.close")}</button>
                    <button ref={doneRef} type="button" className="btn-primary" onClick={() => out.kind === "live" && onSee(out.report)}>
                      <MapPin size={16} aria-hidden="true" />{t("wl.dlg.see")}
                    </button>
                  </>
                ) : <button ref={doneRef} type="button" className="btn-primary" onClick={onClose}>{t("common.close")}</button>}
              </div>
            </div>
          ) : (
            <form className="mt-4" onSubmit={(e) => { e.preventDefault(); send(); }}>
              <label className={`relative grid place-items-center overflow-hidden rounded-lg border-2 border-dashed border-line bg-paper-2 transition-colors has-[:focus-visible]:border-memory has-[:focus-visible]:ring-[2.5px] has-[:focus-visible]:ring-memory ${preview ? "aspect-[16/10]" : "h-36 sm:h-40"} ${busy ? "cursor-default" : "cursor-pointer hover:border-memory"}`}>
                {preview
                  ? <img src={preview} alt="" className="absolute inset-0 h-full w-full object-cover" />
                  : <span className="flex flex-col items-center gap-2 px-4 text-center text-[15.5px] font-semibold text-ink-2"><Camera size={28} aria-hidden="true" />{t("wl.dlg.photo")}</span>}
                {preview && (
                  <span className="absolute bottom-2 right-2 inline-flex items-center gap-1.5 rounded-md bg-paper/90 px-2 py-1 text-[13px] font-semibold text-ink">
                    <Camera size={14} aria-hidden="true" />{t("wl.dlg.photo")}
                  </span>
                )}
                <input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" className="sr-only" disabled={busy}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) pick(f); }} />
              </label>
              {tooBig && <div className="mt-3"><ErrorNote>{t("ev.tooBig")}</ErrorNote></div>}

              <fieldset className="mt-5">
                <legend className="label">{t("wl.dlg.where")}</legend>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                  <button type="button" className="btn-quiet py-2" onClick={locate} disabled={busy || geo.state === "locating"}>
                    {geo.state === "locating" ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <LocateFixed size={16} aria-hidden="true" />}
                    {t("wl.dlg.useLocation")}
                  </button>
                  <div aria-live="polite" className="min-w-0 text-[14.5px] leading-snug">
                    {geo.state === "locating" ? <p className="text-ink-2">{t("wl.dlg.locating")}</p>
                      : geo.state === "located" ? (
                        <p className="flex items-start gap-1.5 text-live">
                          <Check size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
                          <span>{t("wl.dlg.located", { m: geo.acc ?? "-" })}<span className="block text-[13px] tabular-nums text-ink-2">{coords(geo.lat!, geo.lon!)}</span></span>
                        </p>
                      ) : start ? (
                        <p className="flex items-center gap-1.5 text-live"><Check size={16} className="shrink-0" aria-hidden="true" /><span className="tabular-nums text-ink">{coords(start.lat, start.lon)}</span></p>
                      ) : null}
                  </div>
                </div>
                {geo.state === "failed" && (
                  <p className="mt-2 flex items-start gap-1.5 text-[14px] leading-snug text-ink-2">
                    <MapPinOff size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{t("wl.dlg.locFailed")}
                  </p>
                )}
              </fieldset>

              <fieldset className="mt-5">
                <legend className="label">{t("wl.dlg.depth")}</legend>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {DEPTHS.map((d) => (
                    <label key={d} className={busy ? "cursor-default" : "cursor-pointer"}>
                      <input type="radio" name="wl-depth" value={d} checked={depth === d} onChange={() => setDepth(d)} disabled={busy} className="peer sr-only" />
                      <span className="flex h-full flex-col items-center gap-1 rounded-lg border-2 border-line bg-paper px-2 pb-2.5 pt-2 text-center text-[14px] font-semibold leading-tight text-ink-2 transition-colors hover:border-ink-2 peer-checked:border-memory peer-checked:bg-memory-soft/50 peer-checked:text-ink peer-focus-visible:outline peer-focus-visible:outline-[2.5px] peer-focus-visible:outline-offset-2 peer-focus-visible:outline-memory peer-checked:[&>svg]:text-memory">
                        <DepthIcon depth={d} className="h-11 w-11 text-ink-2 transition-colors" />
                        {t(`wl.depth.${d}` as any)}
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div className="mt-5">
                <div className="flex items-baseline justify-between gap-3">
                  <label className="label" htmlFor="wl-note">{t("wl.dlg.note")}</label>
                  <span className="text-[12.5px] tabular-nums text-ink-2" aria-hidden="true">{note.length}/300</span>
                </div>
                <textarea id="wl-note" className="field min-h-[72px] text-[15.5px]" maxLength={300} value={note} disabled={busy} onChange={(e) => setNote(e.target.value)} />
              </div>
              <p className="muted mt-3 flex gap-2 text-[13.5px] leading-snug"><ShieldCheck size={16} className="mt-px shrink-0" aria-hidden="true" />{t("wl.dlg.privacy")}</p>

              {out?.kind === "noLocation" && <div role="alert" className="mt-4 rounded-lg border border-lost/50 bg-lost/10 px-4 py-3 text-[15px]">{t("wl.dlg.noLocation")}</div>}
              {out?.kind === "blocked" && <div className="mt-4"><ErrorNote>{t("wl.dlg.blocked")}</ErrorNote></div>}
              {out?.kind === "error" && <div className="mt-4"><ErrorNote>{out.msg}</ErrorNote></div>}

              <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <button type="button" className="btn-ghost" onClick={onClose}>{t("common.close")}</button>
                <button type="submit" className="btn-primary" disabled={!file || tooBig || busy || geo.state === "locating"}>
                  {busy && <Loader2 size={16} className="animate-spin" aria-hidden="true" />}
                  {phase === "sending" ? t("wl.dlg.sending") : phase === "checking" ? t("wl.dlg.checking") : t("wl.dlg.send")}
                </button>
              </div>
            </form>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
