import { Loader2, Volume2 } from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";

type State = { s: "idle" } | { s: "loading"; v: "hi" | "en" } | { s: "ready"; v: "hi" | "en"; url: string; local: boolean } | { s: "error"; msg: string };

/** The report read aloud by Amazon Polly, in Hindi or English, for people who would rather listen than read. */
export default function ListenButton({ body }: { body: Record<string, unknown> }) {
  const { t } = useT();
  const [st, setSt] = useState<State>({ s: "idle" });
  async function play(v: "hi" | "en") {
    setSt({ s: "loading", v });
    try {
      const r = await api.post<{ url: string; local: boolean }>("/v1/speech", { ...body, lang: v });
      setSt({ s: "ready", v, url: r.url, local: r.local });
    } catch (e: any) {
      setSt({ s: "error", msg: e.message });
    }
  }
  const active = st.s === "loading" || st.s === "ready" ? st.v : null;
  const chip = (v: "hi" | "en", label: string, aria: string) => (
    <button type="button" onClick={() => play(v)} aria-label={aria} aria-pressed={active === v}
      className={`px-3 py-2 text-[15px] font-semibold transition-colors ${active === v ? "bg-ink text-paper" : "bg-paper text-ink hover:bg-paper-2"}`}>
      {label}
    </button>
  );
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="inline-flex items-stretch overflow-hidden rounded-md border border-line" role="group" aria-label={t("listen.button")}>
        <span className="flex items-center gap-1.5 border-r border-line bg-paper-2 px-3 text-[15px] font-semibold">
          {st.s === "loading" ? <Loader2 size={16} className="animate-spin" /> : <Volume2 size={16} aria-hidden="true" />}{t("listen.button")}
        </span>
        {chip("hi", "हिन्दी", t("listen.hi"))}
        <span className="w-px bg-line" aria-hidden="true" />
        {chip("en", "English", t("listen.en"))}
      </div>
      {st.s === "ready" && (
        <div className="flex basis-full flex-col gap-1">
          <audio src={st.url} controls autoPlay className="h-10 w-full max-w-md" />
          <span className="muted text-[12.5px]">{st.local ? t("listen.local") : t("listen.voice")}</span>
        </div>
      )}
      {st.s === "error" && <span className="basis-full text-[14px] text-built">{t("listen.failed", { msg: st.msg })}</span>}
    </div>
  );
}
