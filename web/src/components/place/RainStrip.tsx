import { useQueryClient } from "@tanstack/react-query";
import { BellRing, Check, CloudRain, Loader2 } from "lucide-react";
import { useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { geohash } from "../../lib/geohash";
import { useT } from "../../lib/i18n";
import { useActivity, useForecast } from "../../lib/queries";
import type { ForecastDay } from "../../lib/types";

const HEAVY = new Set(["heavy", "veryHeavy", "extreme"]);

/** Same rule as the server's forecast.should_alert: when a day's rain is worth a heads-up for this place. */
export function worthWarning(d: ForecastDay, tier: string) {
  if (d.mm >= 64.5) return true;
  if (tier === "strong") return d.mm >= 35 || d.maxHourlyMm >= 15;
  if (tier === "some") return d.mm >= 50 || d.maxHourlyMm >= 20;
  return false;
}

function barColor(level: string) {
  return HEAVY.has(level) ? "bg-built" : level === "moderate" ? "bg-lost" : level === "light" ? "bg-memory/70" : "bg-ink-2/30";
}

/** Rain in the next three days at this place, with a warning when it is the kind of rain this place floods in,
 *  and the button to follow the place for an email heads-up. */
export default function RainStrip({ lat, lon, label, tier, nepal }: { lat: number; lon: number; label?: string; tier: string; nepal?: boolean }) {
  const { t, lang } = useT();
  const { user, openAuth } = useAuth();
  const qc = useQueryClient();
  const { data: fc, error } = useForecast(lat, lon);
  const { data: act } = useActivity(!!user);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const gh = geohash(lat, lon);
  const following = !!act?.follows?.some((f) => f.gh7 === gh);
  const days = fc?.days.slice(0, 3) ?? [];
  const top = Math.max(60, ...days.map((d) => d.mm));
  const warnDay = days.slice(0, 2).find((d) => worthWarning(d, tier));
  const dayName = (d: ForecastDay, i: number) =>
    i === 0 ? t("rain.ui.today") : i === 1 ? t("rain.ui.tomorrow") :
      new Date(`${d.date}T00:00:00`).toLocaleDateString(lang === "en" ? "en-IN" : lang, { weekday: "short", day: "numeric", month: "short" });

  async function follow(on: boolean) {
    if (!user) { openAuth("signin", t("auth.needed")); return; }
    setBusy(true);
    setMsg(null);
    try {
      if (on) {
        const r = await api.spost<{ status: string }>("/v1/secure/follows", { lat, lon, label, lang });
        setMsg(r.status === "active" ? t("rain.ui.active") : t("rain.ui.confirm"));
      } else {
        await api.sdel(`/v1/secure/follows/${gh}`);
      }
      await qc.invalidateQueries({ queryKey: ["activity"] });
    } catch (e: any) {
      setMsg(e.decision?.rule ?? e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="rain-title" className="rounded-xl border border-line p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 id="rain-title" className="flex items-center gap-2"><CloudRain size={20} className="text-memory" aria-hidden="true" />{t("rain.ui.title")}</h3>
        {following ? (
          <span className="flex items-center gap-3 text-[15px]">
            <span className="flex items-center gap-1.5 font-semibold text-live"><Check size={16} />{t("rain.ui.following")}</span>
            <button className="link tap text-ink-2" onClick={() => follow(false)} disabled={busy}>{t("rain.ui.unfollow")}</button>
          </span>
        ) : (
          <button className="btn-quiet py-2" onClick={() => follow(true)} disabled={busy}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : <BellRing size={16} aria-hidden="true" />}{t("rain.ui.follow")}
          </button>
        )}
      </div>
      {error ? <p className="muted mt-3 text-[15px]">{t("rain.ui.unavailable")}</p> : (
        <div className="mt-4 grid grid-cols-3 gap-3" aria-busy={!fc}>
          {(fc ? days : [0, 1, 2]).map((d, i) => (
            <div key={i} className="min-w-0">
              <div className="flex h-20 items-end rounded-md bg-paper-2 p-1.5">
                {typeof d === "object" ? (
                  <div className={`w-full rounded-sm ${barColor(d.level)}`} style={{ height: `${Math.max(d.level === "none" ? 5 : 9, (100 * d.mm) / top)}%` }}
                    title={`${d.mm} mm`} />
                ) : <div className="skeleton h-1/3 w-full" />}
              </div>
              {typeof d === "object" && (
                <>
                  <div className="mt-1.5 truncate text-[14px] font-semibold">{dayName(d, i)}</div>
                  <div className="num text-[1.15rem] leading-tight">{t("rain.ui.mm", { mm: Math.round(d.mm * 10) / 10 })}</div>
                  <div className="muted truncate text-[13px]">{t(`rain.level.${d.level}` as any)}{d.prob != null ? `, ${t("rain.ui.chance", { prob: d.prob })}` : ""}</div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
      {warnDay && (
        <p role="alert" className="mt-4 rounded-md border-l-4 border-built bg-built/5 px-3 py-2 text-[15px]">
          {t("rain.ui.heavyWarn", { day: dayName(warnDay, days.indexOf(warnDay)).toLowerCase() })}
        </p>
      )}
      {msg ? <p className="mt-3 text-[14.5px] text-memory">{msg}</p> : !following && <p className="muted mt-3 text-[13.5px]">{t("rain.ui.followHint")}</p>}
      <p className="muted mt-2 text-[12.5px]">{nepal ? t("rain.ui.sourceNp") : t("rain.ui.source")}</p>
    </section>
  );
}
