export type AppConfig = {
  apiBase: string;
  region: string;
  userPoolId?: string;
  userPoolClientId?: string;
  authMode: "cognito" | "local";
  siteUrl?: string;
  mapKey?: string | null;
  mapRegion?: string;
};

let cached: AppConfig | null = null;

/** /config.json is written by deploy.py (API, Cognito ids, map key); the local stack serves its own. */
export async function loadConfig(): Promise<AppConfig> {
  if (cached) return cached;
  try {
    const r = await fetch("/config.json", { cache: "no-store" });
    cached = (await r.json()) as AppConfig;
  } catch {
    cached = { apiBase: "", region: "us-west-2", authMode: "local" };
  }
  return cached!;
}

export function config(): AppConfig {
  return cached ?? { apiBase: "", region: "us-west-2", authMode: "local" };
}
