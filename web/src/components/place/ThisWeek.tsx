import { Check } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { day } from "../../lib/format";
import { useT } from "../../lib/i18n";
import type { Persona } from "../../lib/persona";
import type { Action, PlaceActions } from "../../lib/types";

function readDone(key: string): string[] {
  try { return JSON.parse(localStorage.getItem(key) ?? "[]"); } catch { return []; }
}

/** One step in the reader's language; dates and temperatures are formatted for them. */
export function useActionText() {
  const { t, lang } = useT();
  return (a: Action) => {
    const vars: Record<string, string | number> = {};
    for (const [k, v] of Object.entries(a.vars ?? {})) vars[k] = k === "dates" ? (v as string[]).map((d) => day(d, lang)).join(", ") : (v as any);
    return t(a.key as any, vars);
  };
}

/** What to do this week: the steps for someone renting or buying here, or living here, from the record of this place.
 *  Ticks are kept on this device, so a family can work through the list over a few days. */
export default function ThisWeek({ actions, persona, onPersona, placeKey, extra }: {
  actions: PlaceActions; persona: Persona; onPersona: (p: Persona) => void; placeKey: string;
  extra?: (a: Action) => ReactNode;
}) {
  const { t } = useT();
  const text = useActionText();
  const items = actions[persona] ?? [];
  const storageKey = `js-week-${placeKey}-${persona}`;
  const [done, setDone] = useState<string[]>(() => readDone(storageKey));
  useEffect(() => { setDone(readDone(storageKey)); }, [storageKey]);
  function toggle(key: string) {
    const next = done.includes(key) ? done.filter((k) => k !== key) : [...done, key];
    setDone(next);
    try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* not kept in private mode */ }
  }
  const count = items.filter((a) => done.includes(a.key)).length;
  return (
    <section aria-labelledby="week-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="week-title" className="text-[1.7rem]">{t("week.title")}</h2>
        <div className="inline-flex overflow-hidden rounded-md border border-line text-[14.5px]" role="radiogroup" aria-label={t("persona.label")}>
          {(["home", "resident"] as const).map((p) => (
            <button key={p} role="radio" aria-checked={persona === p} onClick={() => onPersona(p)}
              className={`px-3 py-1.5 font-semibold transition-colors ${persona === p ? "bg-ink text-paper" : "bg-paper text-ink-2 hover:text-ink"}`}>
              {t(`persona.${p}`)}
            </button>
          ))}
        </div>
      </div>
      <p className="muted mt-1.5 text-[15px]">{t(`week.lede.${persona}`)}</p>
      <ol className="mt-3 divide-y divide-line border-y border-line">
        {items.map((a) => {
          const on = done.includes(a.key);
          return (
            <li key={a.key} className="flex gap-3 py-3">
              <button role="checkbox" aria-checked={on} aria-label={text(a)} onClick={() => toggle(a.key)}
                className={`hit mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-[5px] border-2 transition-colors ${on ? "border-live bg-live text-paper" : "border-ink-2/60 bg-paper hover:border-ink"}`}>
                {on && <Check size={15} strokeWidth={3} />}
              </button>
              <div className="min-w-0 flex-1">
                <p className={`text-[15.5px] leading-snug ${on ? "text-ink-2 line-through decoration-ink-2/40" : ""}`}>{text(a)}</p>
                {extra && <div className="mt-2 empty:hidden">{extra(a)}</div>}
              </div>
            </li>
          );
        })}
      </ol>
      <p className="muted mt-2 flex flex-wrap justify-between gap-2 text-[13.5px]">
        <span className="num text-[14px] text-ink">{t("week.done", { n: count, total: items.length })}</span>
        <span>{t("week.saved")}</span>
      </p>
    </section>
  );
}
