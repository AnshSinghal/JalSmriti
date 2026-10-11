import { CloudRain, ExternalLink, FileSearch, FileSignature, MapPin, Waves } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useFindingText } from "../components/bits";
import { CASES, CASE_SUMMARY, VALIDATION, type FloodCase } from "../data/cases";
import { useT } from "../lib/i18n";
import type { Finding } from "../lib/types";

const LEVELS = ["avoid", "think", "checks", "fine"] as const;
const LEVEL_BG: Record<string, string> = { avoid: "bg-built", think: "bg-lost", checks: "bg-memory", fine: "bg-live" };
const LEVEL_TEXT: Record<string, string> = { avoid: "text-built", think: "text-[#9a6206] dark:text-lost", checks: "text-memory", fine: "text-live" };
const TIER_TEXT: Record<string, string> = { strong: "text-built", some: "text-[#9a6206] dark:text-lost", little: "text-memory" };

function share(counts: Record<string, number>) {
  const n = LEVELS.reduce((a, l) => a + (counts[l] ?? 0), 0) || 1;
  return { n, parts: LEVELS.map((l) => ({ l, k: counts[l] ?? 0, pct: (100 * (counts[l] ?? 0)) / n })) };
}

/** One row of the comparison: how the verdict for a ground-floor renter split, as a stacked bar. */
function Bar({ label, counts }: { label: string; counts: Record<string, number> }) {
  const { t } = useT();
  const { n, parts } = share(counts);
  const warned = Math.round(((counts.avoid ?? 0) + (counts.think ?? 0)) * 100 / n);
  return (
    <div className="grid gap-2 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)_5.5rem] sm:items-center sm:gap-4">
      <span className="text-[15px] font-semibold leading-snug">{label}</span>
      <div className="flex h-7 w-full overflow-hidden rounded-md bg-paper-3" role="img"
        aria-label={parts.map((p) => `${t(`verdict.level.${p.l}` as any)} ${p.k}`).join(", ")}>
        {parts.filter((p) => p.k > 0).map((p) => (
          <div key={p.l} className={`${LEVEL_BG[p.l]} flex items-center justify-center text-[12.5px] font-semibold text-white`} style={{ width: `${p.pct}%` }}
            title={`${t(`verdict.level.${p.l}` as any)}: ${p.k}`}>{p.pct >= 7 ? p.k : ""}</div>
        ))}
      </div>
      <span className="num text-[14px] text-ink-2 sm:text-right">{t("proof.warned", { pct: warned })}</span>
    </div>
  );
}

function CaseRow({ c }: { c: FloodCase }) {
  const { t } = useT();
  const text = useFindingText();
  const href = `/place?lat=${c.lat}&lon=${c.lon}&label=${encodeURIComponent(c.label)}`;
  return (
    <article className="grid gap-5 border-t border-line py-8 lg:grid-cols-[minmax(0,4fr)_minmax(0,5fr)_minmax(0,4fr)] lg:gap-8" id={c.id}>
      <div>
        <h3 className="text-[1.45rem] leading-tight">{c.label}</h3>
        <p className="mt-1 text-[14.5px] font-semibold text-ink-2">{c.when}</p>
        <Link to={href} className="btn-quiet tap mt-3"><MapPin size={15} aria-hidden="true" />{t("proof.open")}</Link>
      </div>
      <div className="space-y-2.5 text-[15.5px] leading-snug" lang="en">
        <p><span className="font-semibold">{t("proof.happened")}</span> {c.impact}</p>
        <p><span className="font-semibold">{t("proof.cause")}</span> {c.cause}</p>
        {c.before && <p className="text-ink-2">{c.before}</p>}
        <ul className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-[13px]">
          {c.sources.map((s) => (
            <li key={s.url}><a className="link inline-flex items-center gap-1" href={s.url} target="_blank" rel="noreferrer noopener">{s.title}<ExternalLink size={11} aria-hidden="true" /></a></li>
          ))}
        </ul>
      </div>
      <div className="rounded-lg bg-paper-2 p-4">
        <p className="text-[13px] font-semibold text-ink-2">{t("proof.read")}</p>
        <p className={`display mt-1 text-[1.3rem] leading-tight ${TIER_TEXT[c.tier] ?? ""}`}>
          {t(`place.memory.${c.tier}` as any)} <span className="num text-[1rem] text-ink-2">{t("place.memory.index", { n: c.index })}</span>
        </p>
        <ul className="mt-2 space-y-1 text-[14px] leading-snug">
          {c.findings.slice(0, 3).map((f) => <li key={f.key} className="flex gap-2"><span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ink-2" aria-hidden="true" />{text(f as Finding)}</li>)}
        </ul>
        <p className="mt-3 text-[13px] font-semibold text-ink-2">{t("proof.renter")}</p>
        <dl className="mt-1 grid grid-cols-3 gap-2 text-[13px]">
          {(["ground", "low", "high"] as const).map((fl) => (
            <div key={fl}>
              <dt className="text-ink-2">{t(`verdict.a.${fl}` as any)}</dt>
              <dd className={`font-semibold leading-tight ${LEVEL_TEXT[c.verdict[fl]]}`}>{t(`verdict.level.${c.verdict[fl]}` as any)}</dd>
            </div>
          ))}
        </dl>
      </div>
    </article>
  );
}

const PATTERNS: { key: string; cases: string[] }[] = [
  { key: "notLocal", cases: ["nakkhu", "hafizbabanagar", "velachery"] },
  { key: "permits", cases: ["vitthalnagar", "nallacheruvu", "anilnagar"] },
  { key: "before", cases: ["kendriyavihar", "rainbowdrive", "sailayout"] },
];

const CHANGES: [string, ReactNode][] = [
  ["sign", <FileSignature size={20} />], ["rain", <CloudRain size={20} />], ["buy", <FileSearch size={20} />], ["lake", <Waves size={20} />],
];

const STATS: { key: string; url: string; source: string }[] = [
  { key: "proof.stat.blr", source: "IISc (Ramachandra et al.), via Mongabay", url: "https://www.thequint.com/amp/story/climate-change/as-bengaluru-loses-lakes-green-cover-impact-of-urban-floods-takes-a-toll" },
  { key: "proof.stat.exposed", source: "Rentschler et al., Nature Communications 2022", url: "https://www.nature.com/articles/s41467-022-30727-4" },
  { key: "proof.stat.cost", source: "World Bank, Jul 2025", url: "https://www.worldbank.org/en/news/press-release/2025/07/22/india-has-a-critical-opportunity-to-drive-resilient-urban-development-says-new-world-bank-report" },
  { key: "proof.stat.warning", source: "Global Commission on Adaptation, via WMO", url: "https://wmo.int/node/13544" },
];

export default function Proof() {
  const { t } = useT();
  const byId = Object.fromEntries(CASES.map((c) => [c.id, c]));
  const g = CASE_SUMMARY.groundRenter as Record<string, number>;
  const warned = (g.avoid ?? 0) + (g.think ?? 0);
  return (
    <div className="mx-auto max-w-[1400px] px-4 py-10 sm:px-6">
      <header className="max-w-[60rem]">
        <h1 className="text-[clamp(2.4rem,6vw,4.4rem)] leading-[0.95]">{t("proof.title")}</h1>
        <p className="mt-5 text-[1.15rem] leading-relaxed text-ink-2">{t("proof.lede", { n: CASES.length })}</p>
      </header>

      <section className="mt-12" aria-labelledby="proof-bars">
        <h2 id="proof-bars" className="text-[1.7rem]">{t("proof.bars.title")}</h2>
        <p className="mt-2 max-w-prose text-[16px] leading-snug">{t("proof.bars.lede", { warned, n: CASES.length, avoid: (CASE_SUMMARY.buyer as Record<string, number>).avoid ?? 0 })}</p>
        <div className="mt-6 space-y-4">
          <Bar label={t("proof.bars.cases", { n: CASES.length })} counts={g} />
          <Bar label={t("proof.bars.flooded", { n: VALIDATION.flooded.n })} counts={VALIDATION.flooded} />
          <Bar label={t("proof.bars.random", { n: VALIDATION.random.n })} counts={VALIDATION.random} />
        </div>
        <ul className="mt-4 flex flex-wrap gap-x-5 gap-y-1.5 text-[13.5px] text-ink-2">
          {LEVELS.map((l) => <li key={l} className="flex items-center gap-1.5"><i className={`inline-block h-2.5 w-2.5 rounded-sm ${LEVEL_BG[l]}`} />{t(`verdict.level.${l}` as any)}</li>)}
        </ul>
        <p className="muted mt-3 max-w-prose text-[14px]">{t("proof.bars.note")}</p>
      </section>

      <section className="mt-14" aria-labelledby="proof-patterns">
        <h2 id="proof-patterns" className="text-[1.7rem]">{t("proof.patterns.title")}</h2>
        <div className="mt-5 grid gap-8 md:grid-cols-3">
          {PATTERNS.map((p) => (
            <div key={p.key}>
              <h3 className="text-[1.2rem] leading-tight">{t(`proof.pattern.${p.key}.title` as any)}</h3>
              <p className="mt-1.5 text-[15.5px] leading-snug text-ink-2">{t(`proof.pattern.${p.key}.body` as any)}</p>
              <p className="mt-2 text-[14px]">{p.cases.map((id, i) => <span key={id}>{i > 0 && ", "}<a className="link" href={`#${id}`}>{byId[id]?.label.split(",")[0]}</a></span>)}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-14" aria-labelledby="proof-cases">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="proof-cases" className="text-[1.7rem]">{t("proof.cases.title")}</h2>
          <p className="muted text-[13.5px]">{t("proof.cases.english")}</p>
        </div>
        <div className="mt-4">{CASES.map((c) => <CaseRow key={c.id} c={c} />)}</div>
      </section>

      <section className="mt-10 grid gap-10 border-t border-line pt-10 lg:grid-cols-2" aria-labelledby="proof-change">
        <div>
          <h2 id="proof-change" className="text-[1.7rem]">{t("proof.change.title")}</h2>
          <ul className="mt-4 space-y-4">
            {CHANGES.map(([k, icon]) => (
              <li key={k} className="grid grid-cols-[2rem_1fr] gap-2">
                <span className="mt-0.5 text-memory" aria-hidden="true">{icon}</span>
                <div>
                  <p className="font-semibold leading-snug">{t(`proof.change.${k}.title` as any)}</p>
                  <p className="mt-0.5 text-[15px] leading-snug text-ink-2">{t(`proof.change.${k}.body` as any)}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="rounded-xl border border-line p-5">
            <h2 className="text-[1.4rem]">{t("proof.limits.title")}</h2>
            <ul className="mt-3 list-disc space-y-2 pl-5 text-[15px] leading-snug">
              {(["select", "random", "radar", "guide"] as const).map((k) => <li key={k}>{t(`proof.limits.${k}` as any)}</li>)}
            </ul>
          </div>
          <h2 className="mt-8 text-[1.4rem]">{t("proof.stats.title")}</h2>
          <ul className="mt-3 space-y-3">
            {STATS.map((s) => (
              <li key={s.key} className="text-[15.5px] leading-snug">{t(s.key as any)}{" "}
                <a className="link whitespace-nowrap text-[13px] text-ink-2" href={s.url} target="_blank" rel="noreferrer noopener">{s.source}</a>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
