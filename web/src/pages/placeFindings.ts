import type { Finding } from "../lib/types";

/** Same rules as backend metrics.place_findings, so partial results can be shown while the check runs. */
export function metricsFindingsPlace(s: Record<string, any>): Finding[] {
  const out: Finding[] = [];
  const add = (key: string, severity: Finding["severity"], text: string, vars: Record<string, any> = {}) => out.push({ key, severity, text, vars });
  if ((s.occurrenceHere ?? 0) >= 5) add("wasWater", "high", `Satellites saw water on this very spot in ${s.occurrenceHere}% of looks between 1984 and 2020.`, { pct: s.occurrenceHere });
  if ((s.lostWaterHa300 ?? 0) >= 0.3) add("lostNear", "high", `${s.lostWaterHa300} ha of water that existed within 300 m has disappeared since 1984.`, { ha: s.lostWaterHa300 });
  if ((s.builtOverWaterHa2000 ?? 0) >= 1) add("builtOver", "medium", `Within 2 km, ${s.builtOverWaterHa2000} ha of old water-body beds are now built over.`, { ha: s.builtOverWaterHa2000 });
  if ((s.depressionMax300 ?? 0) >= 1) add("bowl", "medium", `The ground within 300 m forms a bowl up to ${s.depressionMax300.toFixed(1)} m deep where rain can pond.`, { m: Math.round(s.depressionMax300 * 10) / 10 });
  if (s.handMin300 != null && s.handMin300 <= 1) add("lowDrain", "medium", "Part of this place sits less than 1 m above the nearest natural drainage line.");
  for (const r of (s.radarSightings ?? []).slice(0, 6)) add("radar", "high", `Radar saw unusual standing water within 300 m on ${r.date} (${r.haCore} ha).`, { date: r.date, ha: r.haCore });
  if (s.nearestWaterM != null && s.nearestWaterM <= 500 && !out.length) add("nearWater", "info", `The nearest historic water body is ${Math.round(s.nearestWaterM)} m away.`, { m: Math.round(s.nearestWaterM) });
  if (!out.length) add("quiet", "low", "No strong water history was found here in 37 years of satellite records.");
  return out;
}
