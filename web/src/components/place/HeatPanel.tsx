import { Thermometer } from "lucide-react";
import { useT } from "../../lib/i18n";
import type { Heat } from "../../lib/types";

const RAMP = ["#313695", "#74add1", "#fee090", "#f46d43", "#a50026"];   // the image's own colour ramp (heat.py)

function c(v?: number | null) {
  return v == null ? "-" : `${Math.round(v * 10) / 10}`;
}

/** Summer heat at the place: Landsat 8/9 ground temperature on summer mornings, next to built-up ground, lake water
 *  and trees nearby. Lost lakes make neighbourhoods hotter as well as wetter. */
export default function HeatPanel({ heat, older }: { heat?: Heat | null; older?: boolean }) {
  const { t } = useT();
  if (!heat) return older ? (
    <section aria-labelledby="heat-title">
      <h3 id="heat-title" className="flex items-center gap-2"><Thermometer size={20} className="text-built" aria-hidden="true" />{t("heat.title")}</h3>
      <p className="muted mt-1 text-[15px]">{t("heat.older")}</p>
    </section>
  ) : null;
  if (heat.hereC == null) return (
    <section aria-labelledby="heat-title">
      <h3 id="heat-title" className="flex items-center gap-2"><Thermometer size={20} className="text-built" aria-hidden="true" />{t("heat.title")}</h3>
      <p className="muted mt-1 text-[15px]">{t("heat.none")}</p>
    </section>
  );
  const [lo, hi] = heat.scale ?? [25, 50];
  const yrs = heat.years?.length ? `${Math.min(...heat.years)}-${Math.max(...heat.years)}` : "";
  const vb = heat.vsBuiltC;
  const builtLine = vb == null || heat.builtC == null ? null
    : t(vb >= 0.5 ? "heat.vsBuiltWarmer" : vb <= -0.5 ? "heat.vsBuiltCooler" : "heat.vsBuiltSame", { d: c(Math.abs(vb)), built: c(heat.builtC) });
  const waterLine = heat.vsWaterC != null && heat.waterC != null && heat.vsWaterC > 0
    ? t("heat.vsWater", { water: c(heat.waterC), d: c(heat.vsWaterC) }) : null;
  const stats: [string, number | null | undefined, string][] = [
    [t("heat.stat.here"), heat.hereC, "text-built"],
    [t("heat.stat.built"), heat.builtC, "text-ink"],
    [t("heat.stat.water"), heat.waterC, "text-memory"],
    [t("heat.stat.trees"), heat.treesC, "text-live"],
  ];
  return (
    <section aria-labelledby="heat-title">
      <h3 id="heat-title" className="flex items-center gap-2"><Thermometer size={20} className="text-built" aria-hidden="true" />{t("heat.title")}</h3>
      <div className="mt-3 grid gap-5 sm:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] [&>*]:min-w-0">
        {heat.imageUrl && (
          <figure>
            <img src={heat.imageUrl} alt={t("heat.legend")} className="aspect-square w-full rounded-lg border border-line bg-paper-2 object-cover" loading="lazy" />
            <div className="mt-2 h-2.5 w-full rounded-full" style={{ background: `linear-gradient(90deg, ${RAMP.join(", ")})` }} aria-hidden="true" />
            <figcaption className="mt-1 flex justify-between text-[12.5px] text-ink-2">
              <span className="num">{lo} °C</span><span>{t("heat.legend")}</span><span className="num">{hi} °C</span>
            </figcaption>
          </figure>
        )}
        <div className="min-w-0">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
            {stats.filter(([, v]) => v != null).map(([label, v, tone]) => (
              <div key={label}>
                <dt className="muted text-[13.5px] leading-tight">{label}</dt>
                <dd className={`num text-[1.7rem] leading-none ${tone}`}>{c(v)}<span className="ml-0.5 text-[0.95rem] text-ink-2">°C</span></dd>
              </div>
            ))}
          </dl>
          <p className="mt-4 text-[15px] leading-snug">{t("heat.here", { years: yrs, here: c(heat.hereC) })}</p>
          {builtLine && <p className="mt-1.5 text-[15px] leading-snug">{builtLine}</p>}
          {waterLine && <p className="mt-1.5 text-[15px] leading-snug">{waterLine}</p>}
          <p className="muted mt-3 text-[13px]">{t("heat.note")} {t("heat.ring")}</p>
        </div>
      </div>
    </section>
  );
}
