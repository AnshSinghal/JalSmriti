import { useQueries } from "@tanstack/react-query";
import { Building2, ShieldCheck, UserRound } from "lucide-react";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { GradePlate, Spinner } from "../components/bits";
import { api } from "../lib/api";
import { ha, pct } from "../lib/format";
import { useT } from "../lib/i18n";
import { useAreas } from "../lib/queries";
import type { LakeRow } from "../lib/types";

const STEPS = ["s1", "s2", "s3", "s4", "s5"] as const;

export default function Defend() {
  const { t, lang } = useT();
  const nav = useNavigate();
  const { data: areas } = useAreas();
  const ready = (areas ?? []).filter((a) => a.status === "ready");
  const results = useQueries({
    queries: ready.map((a) => ({
      queryKey: ["lakes", a.id], staleTime: 60_000,
      queryFn: () => api.get<{ lakes: LakeRow[] }>(`/v1/areas/${a.id}/lakes`).then((r) => r.lakes),
    })),
  });
  const loading = results.some((r) => r.isLoading);
  const needHelp = useMemo(() => {
    const rows: (LakeRow & { areaId: string })[] = [];
    results.forEach((r, i) => (r.data ?? []).forEach((l) => {
      if (l.kind === "lake" && (l.grade === "D" || l.grade === "E")) rows.push({ ...l, areaId: ready[i].id });
    }));
    return rows.sort((a, b) => (b.lostHa ?? 0) + (b.builtHa ?? 0) - ((a.lostHa ?? 0) + (a.builtHa ?? 0))).slice(0, 14);
  }, [results.map((r) => r.dataUpdatedAt).join(","), ready.length]);
  const areaName = (id: string) => { const a = areas?.find((x) => x.id === id); return a ? a.names[lang] ?? a.names.en : id; };

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6">
      <div className="grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] [&>*]:min-w-0">
        <div>
          <h1 className="max-w-[14ch] text-[clamp(2.4rem,5.6vw,4rem)]">{t("defend.title")}</h1>
          <p className="mt-5 max-w-prose text-[17.5px] text-ink-2">{t("defend.lede")}</p>

          <h2 className="mt-12 text-[1.7rem]">{t("defend.start")}</h2>
          <p className="mt-2 max-w-prose text-[16px] text-ink-2">{t("defend.startLede")}</p>
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="sm:w-64">
              <label className="label" htmlFor="defend-area">{t("defend.pickArea")}</label>
              <select id="defend-area" className="field" defaultValue="" onChange={(e) => e.target.value && nav(`/explore/${e.target.value}`)}>
                <option value="" disabled>{t("explore.area")}</option>
                {(areas ?? []).map((a) => <option key={a.id} value={a.id}>{a.names[lang] ?? a.names.en}</option>)}
              </select>
            </div>
            <Link className="btn-quiet" to="/place?pick=lake">{t("defend.pointMap")}</Link>
          </div>

          <h2 className="mt-12 text-[1.7rem]">{t("defend.roles")}</h2>
          <ul className="mt-4 space-y-4 text-[16px]">
            {([["citizen", UserRound], ["verifier", ShieldCheck], ["officer", Building2]] as const).map(([k, Icon]) => (
              <li key={k} className="flex gap-3">
                <Icon size={20} className="mt-1 shrink-0 text-memory" aria-hidden="true" />
                <span><b className="font-semibold">{t(`me.role.${k}` as any)}.</b> {t(`defend.role.${k}` as any)}</span>
              </li>
            ))}
          </ul>
          <Link className="link mt-4 inline-block text-[15.5px]" to="/about#rules">{t("defend.rulesLink")}</Link>
        </div>

        <ol className="relative mt-2 border-l-2 border-line pl-8 lg:mt-24">
          {STEPS.map((s, i) => (
            <li key={s} className="relative pb-8 last:pb-0">
              <span className="num absolute -left-[3.05rem] top-0 grid h-9 w-9 place-items-center rounded-full border-2 border-line bg-paper text-[1.1rem] text-ink">{i + 1}</span>
              <h3>{t(`defend.${s}.t` as any)}</h3>
              <p className="mt-1.5 max-w-prose text-[16px] text-ink-2">{t(`defend.${s}.b` as any)}</p>
            </li>
          ))}
        </ol>
      </div>

      <section className="mt-20">
        <h2 className="text-[clamp(1.8rem,3.4vw,2.4rem)]">{t("defend.needHelp")}</h2>
        <p className="mt-2 max-w-prose text-[16px] text-ink-2">{t("defend.needHelpLede")}</p>
        {loading && !needHelp.length ? <div className="mt-6"><Spinner label={t("common.loading")} /></div> : (
          <ul className="mt-6 grid gap-x-10 border-t border-line md:grid-cols-2">
            {needHelp.map((l) => (
              <li key={l.lakeId} className="border-b border-line">
                <Link to={`/lake/${l.lakeId}`} className="flex items-center gap-4 py-3.5 hover:text-memory">
                  <GradePlate grade={l.grade} size="sm" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[16.5px] font-semibold">{l.name}</span>
                    <span className="muted text-[13.5px]">
                      {areaName(l.areaId)}{l.lostHa ? `, ${ha(l.lostHa)} ${t("common.ha")} ${t("areas.lost")}` : ""}{l.builtHa ? `, ${ha(l.builtHa)} ${t("common.ha")} ${t("areas.built")}` : ""}{l.weedPct ? `, ${pct(l.weedPct)} ${t("cat.weeds").toLowerCase()}` : ""}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
