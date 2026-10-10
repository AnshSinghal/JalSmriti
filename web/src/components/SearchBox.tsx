import { Loader2, MapPin, Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";

type Result = { label: string; lat: number; lon: number; kind?: string; source?: string };

export const EXAMPLES: Result[] = [
  { label: "Bellandur, Bengaluru", lat: 12.9352, lon: 77.6807 },
  { label: "Velachery, Chennai", lat: 12.9802, lon: 80.2229 },
  { label: "Al Jubail Colony, Hyderabad", lat: 17.3272, lon: 78.4715 },
  { label: "Yamuna Bazar, Delhi", lat: 28.662, lon: 77.2394 },
  { label: "Nazira, Sivasagar", lat: 26.9176, lon: 94.7348 },
];

export function placeUrl(r: { lat: number; lon: number; label?: string }) {
  const q = new URLSearchParams({ lat: r.lat.toFixed(5), lon: r.lon.toFixed(5) });
  if (r.label) q.set("label", r.label);
  return `/place?${q.toString()}`;
}

export default function SearchBox({ autoFocus, large, showExamples = true, onPick, placeholder, inputRef }: {
  autoFocus?: boolean; large?: boolean; showExamples?: boolean; onPick?: (r: Result) => void; placeholder?: string;
  inputRef?: React.Ref<HTMLInputElement>;
}) {
  const { t } = useT();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState(-1);
  const listId = useId();
  const seq = useRef(0);

  useEffect(() => {
    const text = q.trim();
    if (text.length < 3) { setResults([]); return; }
    const my = ++seq.current;
    setBusy(true);
    const h = window.setTimeout(async () => {
      try {
        const r = await api.get<{ results: Result[] }>(`/v1/geocode?q=${encodeURIComponent(text)}`);
        if (my === seq.current) { setResults(r.results); setOpen(true); setActive(-1); }
      } catch {
        if (my === seq.current) setResults([]);
      } finally {
        if (my === seq.current) setBusy(false);
      }
    }, 320);
    return () => window.clearTimeout(h);
  }, [q]);

  function go(r: Result) {
    setOpen(false);
    if (onPick) onPick(r);
    else nav(placeUrl(r));
  }

  return (
    <div className="w-full">
      <label htmlFor={`${listId}-in`} className="sr-only">{t("hero.searchLabel")}</label>
      <div className="relative">
        <div className={`flex items-center gap-2 rounded-lg border-2 border-ink bg-paper pl-3.5 pr-1.5 focus-within:border-memory ${large ? "h-[3.6rem]" : "h-12"}`}>
          {busy ? <Loader2 size={20} className="shrink-0 animate-spin text-ink-2" /> : <Search size={20} className="hidden shrink-0 text-ink-2 sm:block" />}
          <input id={`${listId}-in`} ref={inputRef} autoFocus={autoFocus} value={q} onChange={(e) => setQ(e.target.value)}
            onFocus={() => results.length && setOpen(true)} onBlur={() => window.setTimeout(() => setOpen(false), 160)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { setActive((a) => Math.min(a + 1, results.length - 1)); e.preventDefault(); }
              if (e.key === "ArrowUp") { setActive((a) => Math.max(a - 1, 0)); e.preventDefault(); }
              if (e.key === "Enter" && results.length) go(results[Math.max(active, 0)]);
              if (e.key === "Escape") setOpen(false);
            }}
            placeholder={placeholder ?? t("hero.searchPlaceholder")} autoComplete="off" role="combobox" aria-expanded={open}
            aria-controls={`${listId}-list`} aria-autocomplete="list"
            className={`min-w-0 flex-1 self-stretch bg-transparent outline-none placeholder:text-ink-2/70 ${large ? "text-[1.1rem]" : "text-[16px]"}`} />
          <button className="btn-primary h-[calc(100%-10px)] px-3.5 sm:px-4" aria-label={t("hero.searchLabel")}
            onClick={() => results.length ? go(results[Math.max(active, 0)]) : nav("/place?pick=1")}>
            <Search size={19} className="sm:hidden" aria-hidden="true" /><span className="hidden sm:inline">{t("hero.searchLabel")}</span>
          </button>
        </div>
        {open && (
          <ul id={`${listId}-list`} role="listbox" className="absolute left-0 right-0 top-[calc(100%+6px)] z-30 overflow-hidden rounded-lg border border-line bg-paper shadow-xl">
            {results.length === 0 && !busy && <li className="muted px-4 py-3 text-[15px]">{t("search.noResults")}</li>}
            {results.map((r, i) => (
              <li key={`${r.lat},${r.lon},${i}`} role="option" aria-selected={i === active}>
                <button onMouseDown={(e) => e.preventDefault()} onClick={() => go(r)}
                  className={`flex w-full items-start gap-2.5 px-4 py-2.5 text-left text-[15.5px] ${i === active ? "bg-paper-2" : "hover:bg-paper-2"}`}>
                  <MapPin size={17} className="mt-0.5 shrink-0 text-ink-2" />
                  <span>{r.label}</span>
                </button>
              </li>
            ))}
            <li className="border-t border-line">
              <button onMouseDown={(e) => e.preventDefault()} onClick={() => nav("/place?pick=1")} className="w-full px-4 py-2.5 text-left text-[15px] text-memory hover:bg-paper-2">
                {t("search.useMap")}
              </button>
            </li>
          </ul>
        )}
      </div>
      {showExamples && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="muted text-[14px]">{t("hero.try")}</span>
          {EXAMPLES.map((e) => <button key={e.label} className="chip" onClick={() => go(e)}>{e.label}</button>)}
        </div>
      )}
    </div>
  );
}
