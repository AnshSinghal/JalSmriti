import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import en from "../i18n/en";

export const LANGUAGES = [
  { code: "en", name: "English" },
  { code: "hi", name: "हिन्दी" },
  { code: "kn", name: "ಕನ್ನಡ" },
  { code: "ta", name: "தமிழ்" },
  { code: "te", name: "తెలుగు" },
  { code: "ml", name: "മലയാളം" },
  { code: "ne", name: "नेपाली" },
] as const;
export type Lang = (typeof LANGUAGES)[number]["code"];
export type Dict = Partial<Record<keyof typeof en, string>>;

const loaders: Record<Exclude<Lang, "en">, () => Promise<{ default: Dict }>> = {
  hi: () => import("../i18n/hi"),
  kn: () => import("../i18n/kn"),
  ta: () => import("../i18n/ta"),
  te: () => import("../i18n/te"),
  ml: () => import("../i18n/ml"),
  ne: () => import("../i18n/ne"),
};

type Ctx = { lang: Lang; setLang: (l: Lang) => void; t: (k: keyof typeof en, vars?: Record<string, string | number>) => string };
const I18nContext = createContext<Ctx | null>(null);

function initial(): Lang {
  try {
    const s = localStorage.getItem("js-lang") as Lang | null;
    if (s && LANGUAGES.some((l) => l.code === s)) return s;
  } catch { /* ignore */ }
  const nav = (navigator.language || "en").slice(0, 2) as Lang;
  return LANGUAGES.some((l) => l.code === nav) ? nav : "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initial);
  const [dict, setDict] = useState<Dict>({});

  useEffect(() => {
    document.documentElement.setAttribute("lang", lang);
    try { localStorage.setItem("js-lang", lang); } catch { /* ignore */ }
    if (lang === "en") { setDict({}); return; }
    let alive = true;
    loaders[lang]().then((m) => alive && setDict(m.default));
    return () => { alive = false; };
  }, [lang]);

  const t = useCallback((k: keyof typeof en, vars?: Record<string, string | number>) => {
    let s = (dict[k] ?? en[k] ?? String(k)) as string;
    if (vars) for (const [name, v] of Object.entries(vars)) s = s.split(`{${name}}`).join(String(v));
    return s;
  }, [dict]);

  const value = useMemo(() => ({ lang, setLang: setLangState, t }), [lang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useT() {
  const c = useContext(I18nContext);
  if (!c) throw new Error("I18nProvider missing");
  return c;
}
