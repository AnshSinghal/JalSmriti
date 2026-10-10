import { config } from "./config";
import { currentToken } from "./auth";

export class ApiError extends Error {
  status: number;
  decision?: { explanation?: string; rule?: string; policies?: string[] };
  constructor(status: number, message: string, decision?: ApiError["decision"]) {
    super(message);
    this.status = status;
    this.decision = decision;
  }
}

async function call<T>(method: string, path: string, body?: unknown, auth = false): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["content-type"] = "application/json";
  if (auth) {
    const t = await currentToken();
    if (!t) throw new ApiError(401, "Sign in first");
    headers.authorization = `Bearer ${t}`;
  }
  const r = await fetch(`${config().apiBase}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { message: text };
  }
  if (!r.ok) {
    let msg = data?.message ?? r.statusText;
    let decision;
    if (typeof msg === "string" && msg.startsWith("{")) {
      try {
        const inner = JSON.parse(msg);
        msg = inner.message;
        decision = inner.decision;
      } catch {
        /* keep message */
      }
    }
    throw new ApiError(r.status, msg || `Request failed (${r.status})`, decision ?? data?.decision);
  }
  return data as T;
}

export const api = {
  get: <T>(p: string) => call<T>("GET", p),
  post: <T>(p: string, b?: unknown) => call<T>("POST", p, b ?? {}),
  sget: <T>(p: string) => call<T>("GET", p, undefined, true),
  spost: <T>(p: string, b?: unknown) => call<T>("POST", p, b ?? {}, true),
  sdel: <T>(p: string) => call<T>("DELETE", p, undefined, true),
};

/** Upload a photo straight to S3 with the presigned POST the API returned. */
export async function uploadToS3(upload: { url: string; fields: Record<string, string> }, file: File) {
  const fd = new FormData();
  Object.entries(upload.fields).forEach(([k, v]) => fd.append(k, v));
  fd.append("file", file);
  const r = await fetch(upload.url, { method: "POST", body: fd });
  if (!r.ok && r.status !== 204) throw new ApiError(r.status, "The photo could not be uploaded");
}
