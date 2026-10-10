import { useEffect, useState } from "react";

/** Who the steps on a place page are for: someone renting or buying there, or someone living there. Chosen on the
 *  home page or on the place page, remembered on this device only. */
export type Persona = "home" | "resident";
const KEY = "js-persona";
const EVENT = "js-persona";

export function getPersona(): Persona {
  try {
    return localStorage.getItem(KEY) === "resident" ? "resident" : "home";
  } catch {
    return "home";
  }
}

export function setPersona(p: Persona) {
  try { localStorage.setItem(KEY, p); } catch { /* private mode: keep it for this page only */ }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: p }));
}

export function usePersona(): [Persona, (p: Persona) => void] {
  const [p, setP] = useState<Persona>(getPersona);
  useEffect(() => {
    const on = (e: Event) => setP((e as CustomEvent).detail as Persona);
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  return [p, setPersona];
}
