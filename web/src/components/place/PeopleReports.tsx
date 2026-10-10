import { Camera, Droplets } from "lucide-react";
import { Link } from "react-router-dom";
import { day } from "../../lib/format";
import { useT } from "../../lib/i18n";
import { useNearby } from "../../lib/queries";

/** Standing water that people reported within 1 km in the last year: the street-level record satellites miss. */
export default function PeopleReports({ lat, lon }: { lat: number; lon: number }) {
  const { t, lang } = useT();
  const { data } = useNearby(lat, lon);
  const reportUrl = `/waterlogging?report=1&lat=${lat.toFixed(5)}&lon=${lon.toFixed(5)}`;
  return (
    <section aria-labelledby="people-title">
      <h3 id="people-title" className="flex items-center gap-2"><Droplets size={20} className="text-memory" aria-hidden="true" />{t("wl.near.title")}</h3>
      {data && (data.count > 0 ? (
        <>
          <p className="mt-1 text-[15px]">{t(data.count === 1 ? "wl.near.one" : "wl.near.some", { n: data.count, date: day(data.lastSeenAt ?? data.items[0]?.seenAt, lang) })}</p>
          <ul className="mt-3 grid grid-cols-4 gap-2">
            {data.items.slice(0, 4).map((r) => (
              <li key={r.reportId}>
                <a href={r.url} target="_blank" rel="noreferrer" className="block aspect-square overflow-hidden rounded-md bg-paper-3"
                  title={`${day(r.seenAt, lang)}${r.depth ? `, ${t(`wl.depth.${r.depth}` as any)}` : ""}`}>
                  {r.thumbUrl && <img src={r.thumbUrl} alt={r.ai?.summary ?? ""} className="h-full w-full object-cover" loading="lazy" />}
                </a>
              </li>
            ))}
          </ul>
        </>
      ) : <p className="muted mt-1 text-[15px]">{t("wl.near.none")}</p>)}
      <Link className="btn-quiet mt-3" to={reportUrl}><Camera size={16} aria-hidden="true" />{t("wl.near.report")}</Link>
    </section>
  );
}
