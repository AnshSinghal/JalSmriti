import { dateTime } from "../lib/format";
import { useT } from "../lib/i18n";
import type { TimelineEntry } from "../lib/types";

const TONE: Record<string, string> = {
  drafting: "bg-ink-2", ready: "bg-memory", submitted: "bg-ink", acknowledged: "bg-live", action_taken: "bg-live",
  rejected: "bg-built", closed: "bg-ink-2", failed: "bg-built",
};

/** A dossier's progress as marks on a staff: each step is a short tick off one vertical line, newest last. */
export default function Timeline({ entries }: { entries: TimelineEntry[] }) {
  const { t, lang } = useT();
  if (!entries.length) return null;
  return (
    <ol className="relative ml-1 border-l-2 border-line">
      {entries.map((e, i) => (
        <li key={`${e.at}-${i}`} className="relative pb-5 pl-5 last:pb-0">
          <span className={`absolute -left-[2px] top-[0.72em] h-[3px] w-3.5 ${TONE[e.status] ?? "bg-ink-2"}`} aria-hidden="true" />
          <div className="font-semibold leading-snug">{e.status === "drafting" ? t("dossier.event.drafting") : t(`dossier.status.${e.status}` as any)}</div>
          <div className="muted text-[13.5px]">{dateTime(e.at, lang)}, {e.by}</div>
          {e.note && <p className="mt-0.5 text-[14.5px] leading-snug">{e.note}</p>}
        </li>
      ))}
    </ol>
  );
}
