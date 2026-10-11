import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Check, Loader2, Minus, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { day } from "../../lib/format";
import { useT } from "../../lib/i18n";
import type { Persona } from "../../lib/persona";

export type Answers = { mode: "rent" | "buy"; floor: "ground" | "low" | "high" | "house"; parking: boolean; vulnerable: boolean };
type Item = { key: string; vars?: Record<string, any> };
export type Verdict = {
  level: "avoid" | "think" | "checks" | "fine"; points: number; placePoints: number; answers: Answers;
  headline: Item; why: Item[]; pros: Item[]; cons: Item[]; ifStill: Item[]; note: Item;
};

const KEY = "js-verdict";
const EVENT = "js-verdict";
const DEFAULTS: Answers = { mode: "rent", floor: "ground", parking: false, vulnerable: false };

function readAnswers(): Answers {
  try {
    const a = JSON.parse(localStorage.getItem(KEY) ?? "{}");
    return {
      mode: a.mode === "buy" ? "buy" : "rent",
      floor: ["ground", "low", "high", "house"].includes(a.floor) ? a.floor : "ground",
      parking: a.parking === true, vulnerable: a.vulnerable === true,
    };
  } catch {
    return DEFAULTS;
  }
}

/** The four answers of the family, kept on this device only (the same answers go into the signed report). */
export function useAnswers(): [Answers, (a: Answers) => void] {
  const [a, setA] = useState<Answers>(readAnswers);
  useEffect(() => {
    const on = (e: Event) => setA((e as CustomEvent).detail as Answers);
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  const set = (next: Answers) => {
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* private mode: this page only */ }
    window.dispatchEvent(new CustomEvent(EVENT, { detail: next }));
  };
  return [a, set];
}

/** A verdict line in the reader's language: dates formatted, nested keys worded. */
function useItemText() {
  const { t, lang } = useT();
  return (it: Item) => {
    const vars: Record<string, string | number> = {};
    for (const [k, v] of Object.entries(it.vars ?? {})) {
      if (v && typeof v === "object" && "key" in v) vars[k] = t((v as Item).key as any);
      else if (k === "dates") vars[k] = (v as string[]).map((d) => day(d, lang)).join(", ");
      else vars[k] = v as any;
    }
    return t(it.key as any, vars);
  };
}

const LEVEL: Record<Verdict["level"], { bar: string; text: string; bg: string }> = {
  avoid: { bar: "bg-built", text: "text-built", bg: "bg-built/[0.07]" },
  think: { bar: "bg-lost", text: "text-[#9a6206] dark:text-lost", bg: "bg-lost/10" },
  checks: { bar: "bg-memory", text: "text-memory", bg: "bg-memory/[0.07]" },
  fine: { bar: "bg-live", text: "text-live", bg: "bg-live/10" },
};

function Choice<T extends string | boolean>({ label, value, options, onPick }: {
  label: string; value: T; options: [T, string][]; onPick: (v: T) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <span className="text-[14.5px] font-semibold">{label}</span>
      <div role="radiogroup" aria-label={label}
        className={`${options.length > 2 ? "grid grid-cols-2 sm:inline-flex" : "inline-flex"} overflow-hidden rounded-md border border-line text-[14px]`}>
        {options.map(([v, text]) => (
          <button key={String(v)} role="radio" aria-checked={value === v} onClick={() => onPick(v)}
            className={`px-3 py-1.5 font-semibold transition-colors ${value === v ? "bg-ink text-paper" : "bg-paper text-ink-2 hover:text-ink"}`}>
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Our read for a family about to rent or buy here: four quick answers, then a clear verdict with why, what is in
 *  its favour and against it, and what to do if they still like the place. */
export default function VerdictCard({ lat, lon, persona, onPersona }: {
  lat: number; lon: number; persona: Persona; onPersona: (p: Persona) => void;
}) {
  const { t } = useT();
  const text = useItemText();
  const [a, setA] = useAnswers();
  const q = `/v1/places/verdict?lat=${lat}&lon=${lon}&mode=${a.mode}&floor=${a.floor}&parking=${a.parking ? 1 : 0}&vulnerable=${a.vulnerable ? 1 : 0}`;
  const { data: v, isFetching, error } = useQuery({
    queryKey: ["verdict", lat, lon, a], enabled: persona === "home", queryFn: () => api.get<Verdict>(q),
    placeholderData: keepPreviousData, staleTime: 10 * 60_000,
  });

  if (persona !== "home") {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line px-4 py-3">
        <p className="text-[15px]">{t("verdict.ui.ask")}</p>
        <button className="btn-quiet" onClick={() => onPersona("home")}>{t("verdict.ui.get")}</button>
      </div>
    );
  }
  const style = v ? LEVEL[v.level] : LEVEL.checks;
  return (
    <section aria-labelledby="verdict-title" className="rounded-xl border border-line">
      <div className="space-y-3 border-b border-line p-4 sm:p-5">
        <div className="flex items-baseline justify-between gap-3">
          <h2 id="verdict-title" className="text-[1.7rem]">{t("verdict.title")}</h2>
          {isFetching && <Loader2 size={16} className="animate-spin text-ink-2" aria-label={t("common.loading")} />}
        </div>
        <Choice label={t("verdict.q.mode")} value={a.mode} onPick={(mode) => setA({ ...a, mode })}
          options={[["rent", t("verdict.a.rent")], ["buy", t("verdict.a.buy")]]} />
        <Choice label={t("verdict.q.floor")} value={a.floor} onPick={(floor) => setA({ ...a, floor })}
          options={[["ground", t("verdict.a.ground")], ["low", t("verdict.a.low")], ["high", t("verdict.a.high")], ["house", t("verdict.a.house")]]} />
        <Choice label={t("verdict.q.parking")} value={a.parking} onPick={(parking) => setA({ ...a, parking })}
          options={[[false, t("verdict.a.no")], [true, t("verdict.a.yes")]]} />
        <Choice label={t("verdict.q.vulnerable")} value={a.vulnerable} onPick={(vulnerable) => setA({ ...a, vulnerable })}
          options={[[false, t("verdict.a.no")], [true, t("verdict.a.yes")]]} />
      </div>
      {error && !v && <p className="p-5 text-[15px] text-built">{(error as Error).message}</p>}
      {v && (
        <div className="p-4 sm:p-5" aria-live="polite">
          <div className={`relative overflow-hidden rounded-lg ${style.bg} py-3 pl-5 pr-4`}>
            <span className={`absolute inset-y-0 left-0 w-1.5 ${style.bar}`} aria-hidden="true" />
            <p className={`display text-[1.35rem] leading-tight ${style.text}`}>{t(`verdict.level.${v.level}` as any)}</p>
            <p className="mt-1 text-[17px] font-semibold leading-snug">{text(v.headline)}</p>
          </div>
          <h3 className="mt-5 text-[1.1rem]">{t("verdict.why")}</h3>
          <ul className="mt-1.5 space-y-1.5">
            {v.why.map((it) => <li key={it.key} className="flex gap-2.5 text-[15.5px] leading-snug"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-2" aria-hidden="true" />{text(it)}</li>)}
          </ul>
          {(v.pros.length > 0 || v.cons.length > 0) && (
            <div className="mt-5 grid gap-5 sm:grid-cols-2">
              <div>
                <h3 className="text-[1.1rem]">{t("verdict.pros")}</h3>
                {v.pros.length ? (
                  <ul className="mt-1.5 space-y-1.5">
                    {v.pros.map((it) => <li key={it.key} className="flex gap-2 text-[15px] leading-snug"><Plus size={16} className="mt-0.5 shrink-0 text-live" aria-hidden="true" />{text(it)}</li>)}
                  </ul>
                ) : <p className="muted mt-1.5 text-[14.5px]">{t("verdict.ui.nonePros")}</p>}
              </div>
              <div>
                <h3 className="text-[1.1rem]">{t("verdict.cons")}</h3>
                {v.cons.length ? (
                  <ul className="mt-1.5 space-y-1.5">
                    {v.cons.map((it) => <li key={it.key} className="flex gap-2 text-[15px] leading-snug"><Minus size={16} className="mt-0.5 shrink-0 text-built" aria-hidden="true" />{text(it)}</li>)}
                  </ul>
                ) : <p className="muted mt-1.5 text-[14.5px]">{t("verdict.ui.noneCons")}</p>}
              </div>
            </div>
          )}
          <h3 className="mt-5 text-[1.1rem]">{t("verdict.ifStill")}</h3>
          <ul className="mt-1.5 space-y-1.5">
            {v.ifStill.map((it) => <li key={it.key} className="flex gap-2 text-[15px] leading-snug"><Check size={16} className="mt-0.5 shrink-0 text-memory" aria-hidden="true" />{text(it)}</li>)}
          </ul>
          <p className="muted mt-4 text-[13px] leading-snug">{text(v.note)}</p>
        </div>
      )}
    </section>
  );
}
