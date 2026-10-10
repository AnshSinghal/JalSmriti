export function ha(v?: number | null, digits?: number): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  const d = digits ?? (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 1);
  return v.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: 0 });
}
export function pct(v?: number | null): string {
  if (v === null || v === undefined) return "-";
  return `${Math.round(v)}%`;
}
export function int(v?: number | null): string {
  if (v === null || v === undefined) return "-";
  return Math.round(v).toLocaleString("en-IN");
}
export function day(iso?: string | null, lang = "en"): string {
  if (!iso) return "-";
  const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
  try {
    return d.toLocaleDateString(lang === "en" ? "en-IN" : lang, { day: "numeric", month: "short", year: "numeric" });
  } catch {
    return d.toDateString();
  }
}
export function dateTime(iso?: string | null, lang = "en"): string {
  if (!iso) return "-";
  const d = new Date(iso);
  try {
    return d.toLocaleString(lang === "en" ? "en-IN" : lang, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return d.toString();
  }
}
export function shortHash(h?: string | null, n = 12): string {
  return h ? `${h.slice(0, n)}…` : "-";
}
export function gradeColor(g?: string | null): string {
  switch (g) {
    case "A": return "rgb(var(--memory))";
    case "B": return "#3D7FC4";
    case "C": return "rgb(var(--lost))";
    case "D": return "#E0662C";
    case "E": return "rgb(var(--built))";
    default: return "rgb(var(--ink-2))";
  }
}
