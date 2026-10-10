import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.getAttribute("data-theme") as Theme) || "light");
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("js-theme", theme); } catch { /* ignore */ }
    window.dispatchEvent(new CustomEvent("js-theme", { detail: theme }));
  }, [theme]);
  return [theme, setTheme];
}

/** Re-render on theme changes (the map swaps basemap styles). */
export function useThemeValue(): Theme {
  const [t, setT] = useState<Theme>(() => (document.documentElement.getAttribute("data-theme") as Theme) || "light");
  useEffect(() => {
    const on = (e: Event) => setT((e as CustomEvent).detail);
    window.addEventListener("js-theme", on);
    return () => window.removeEventListener("js-theme", on);
  }, []);
  return t;
}
