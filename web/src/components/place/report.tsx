import { CheckCircle2, Download, FileSignature, Loader2, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { LANGUAGES, useT } from "../../lib/i18n";
import type { Persona } from "../../lib/persona";
import type { PlaceReport } from "../../lib/types";
import { ErrorNote } from "../bits";
import type { Answers } from "./VerdictCard";

export type ReportState = { s: "idle" } | { s: "working" } | { s: "ready"; r: PlaceReport } | { s: "error"; msg: string };

/** The signed place report: requested in the reader's language for the chosen reader, rendered and signed by the jobs
 *  worker, then offered for download. Asking again for the same check returns the same signed PDF. */
export function usePlaceReport(lat: number, lon: number, label: string | undefined, persona: Persona, answers?: Answers) {
  const { lang } = useT();
  const [st, setSt] = useState<ReportState>({ s: "idle" });
  const alive = useRef(true);
  const answersKey = answers ? JSON.stringify(answers) : "";
  useEffect(() => () => { alive.current = false; }, []);
  useEffect(() => { setSt({ s: "idle" }); }, [lang, persona, answersKey]);

  async function start() {
    setSt({ s: "working" });
    try {
      let r = await api.post<PlaceReport>("/v1/places/report", { lat, lon, label, lang, persona, answers });
      for (let i = 0; i < 60 && r.status === "rendering" && alive.current; i++) {
        await new Promise((res) => setTimeout(res, 2000));
        r = await api.get<PlaceReport>(`/v1/reports/${r.reportId}`);
      }
      if (!alive.current) return;
      if (r.status === "ready") setSt({ s: "ready", r });
      else setSt({ s: "error", msg: r.error ?? r.status });
    } catch (e: any) {
      if (alive.current) setSt({ s: "error", msg: e.message });
    }
  }
  return { state: st, start };
}

export function ReportButton({ state, start }: { state: ReportState; start: () => void }) {
  const { t } = useT();
  return (
    <button className="btn-memory" onClick={start} disabled={state.s === "working"}>
      {state.s === "working" ? <Loader2 size={16} className="animate-spin" /> : <FileSignature size={16} aria-hidden="true" />}
      {t("report.ui.button")}
    </button>
  );
}

export function ReportStatus({ state }: { state: ReportState }) {
  const { t, lang } = useT();
  if (state.s === "idle") return null;
  const langName = LANGUAGES.find((l) => l.code === lang)?.name ?? "English";
  return (
    <div className="mt-4" aria-live="polite">
      {state.s === "working" && (
        <p className="flex items-center gap-2 text-[15.5px]"><Loader2 size={17} className="animate-spin text-memory" />{t("report.ui.preparing")}</p>
      )}
      {state.s === "ready" && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-live/40 bg-live/5 px-4 py-3">
          <span className="flex items-center gap-2 text-[15.5px] font-semibold"><CheckCircle2 size={18} className="text-live" />{t("report.ui.ready")}</span>
          <a className="btn-primary px-3 py-2" href={state.r.pdfUrl} target="_blank" rel="noreferrer" download><Download size={16} />{t("report.ui.download")}</a>
          <Link className="link text-[15px]" to={`/verify/${state.r.reportId}`}><ShieldCheck size={15} className="mr-1 inline" />{t("report.ui.verify")}</Link>
          <span className="muted basis-full text-[13.5px]">{t("report.ui.hint", { lang: langName })}</span>
        </div>
      )}
      {state.s === "error" && <ErrorNote>{t("report.ui.failed", { msg: state.msg })}</ErrorNote>}
    </div>
  );
}
