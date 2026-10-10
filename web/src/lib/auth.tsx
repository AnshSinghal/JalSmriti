import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { config } from "./config";

/** Amazon Cognito sign-in without an SDK: the public Cognito user-pool API takes plain JSON over fetch.
 *  In the local stack (authMode "local") the same calls go to /local-auth on the local server. */

export type User = {
  sub: string;
  email?: string;
  role: "citizen" | "verifier" | "officer" | "admin";
  groups: string[];
  jurisdictions: string[];
  exp: number;
};

type Tokens = { idToken: string; refreshToken?: string; exp: number };
const KEY = "js-auth";

function store(t: Tokens | null) {
  try {
    if (t) localStorage.setItem(KEY, JSON.stringify(t));
    else localStorage.removeItem(KEY);
  } catch {
    /* private mode: stay signed in for this tab only */
  }
  memory = t;
}
let memory: Tokens | null = null;
function load(): Tokens | null {
  if (memory) return memory;
  try {
    const v = localStorage.getItem(KEY);
    memory = v ? (JSON.parse(v) as Tokens) : null;
  } catch {
    memory = null;
  }
  return memory;
}

function decode(token: string): Record<string, any> {
  const part = token.split(".")[1] ?? "";
  const b64 = part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "=");
  const json = decodeURIComponent(
    atob(b64).split("").map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2)).join(""),
  );
  return JSON.parse(json);
}

export function userFromToken(token: string): User {
  const c = decode(token);
  const groups: string[] = Array.isArray(c["cognito:groups"]) ? c["cognito:groups"] : [];
  const role = (["admin", "officer", "verifier"].find((r) => groups.includes(r)) as User["role"]) ?? "citizen";
  const jur = String(c["custom:jurisdictions"] ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  return { sub: c.sub, email: c.email, role, groups, jurisdictions: jur, exp: c.exp };
}

async function cognito(target: string, body: Record<string, unknown>): Promise<any> {
  const cfg = config();
  if (cfg.authMode === "local") {
    const r = await fetch(`/local-auth/${target}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.message ?? "Sign-in failed");
    return d;
  }
  const r = await fetch(`https://cognito-idp.${cfg.region}.amazonaws.com/`, {
    method: "POST",
    headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}` },
    body: JSON.stringify({ ClientId: cfg.userPoolClientId, ...body }),
  });
  const d = await r.json();
  if (!r.ok) {
    const type = String(d.__type ?? "").split("#").pop();
    const friendly: Record<string, string> = {
      NotAuthorizedException: "That email and password do not match.",
      UserNotConfirmedException: "Confirm your email first: enter the code we sent you.",
      UsernameExistsException: "An account with this email already exists. Sign in instead.",
      CodeMismatchException: "That code is not right. Check the latest email.",
      ExpiredCodeException: "That code has expired. Send a new one.",
      InvalidPasswordException: "Use at least 10 characters with upper and lower case letters and a number.",
      LimitExceededException: "Too many attempts. Wait a few minutes and try again.",
      TooManyRequestsException: "Too many attempts. Wait a few minutes and try again.",
    };
    const err = new Error(friendly[type ?? ""] ?? d.message ?? "Sign-in failed");
    (err as any).code = type;
    throw err;
  }
  return d;
}

export async function currentToken(): Promise<string | null> {
  const t = load();
  if (!t) return null;
  if (t.exp * 1000 - Date.now() > 60_000) return t.idToken;
  if (!t.refreshToken) {
    store(null);
    return null;
  }
  try {
    const d = await cognito("InitiateAuth", { AuthFlow: "REFRESH_TOKEN_AUTH", AuthParameters: { REFRESH_TOKEN: t.refreshToken } });
    const idToken = d.AuthenticationResult.IdToken as string;
    store({ idToken, refreshToken: t.refreshToken, exp: decode(idToken).exp });
    return idToken;
  } catch {
    store(null);
    return null;
  }
}

type Ctx = {
  user: User | null;
  ready: boolean;
  dialog: null | { mode: "signin" | "signup"; reason?: string };
  openAuth: (mode?: "signin" | "signup", reason?: string) => void;
  closeAuth: () => void;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  confirm: (email: string, code: string) => Promise<void>;
  resend: (email: string) => Promise<void>;
  forgot: (email: string) => Promise<void>;
  resetPassword: (email: string, code: string, password: string) => Promise<void>;
  signOut: () => void;
};
const AuthContext = createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [dialog, setDialog] = useState<Ctx["dialog"]>(null);

  useEffect(() => {
    currentToken().then((t) => {
      setUser(t ? userFromToken(t) : null);
      setReady(true);
    });
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const d = await cognito("InitiateAuth", { AuthFlow: "USER_PASSWORD_AUTH", AuthParameters: { USERNAME: email.trim().toLowerCase(), PASSWORD: password } });
    if (!d.AuthenticationResult) throw new Error("This account needs a new password. Use 'Forgot password'.");
    const idToken = d.AuthenticationResult.IdToken as string;
    store({ idToken, refreshToken: d.AuthenticationResult.RefreshToken, exp: decode(idToken).exp });
    setUser(userFromToken(idToken));
  }, []);

  const value = useMemo<Ctx>(() => ({
    user, ready, dialog,
    openAuth: (mode = "signin", reason) => setDialog({ mode, reason }),
    closeAuth: () => setDialog(null),
    signIn,
    signUp: async (email, password) => {
      await cognito("SignUp", { Username: email.trim().toLowerCase(), Password: password, UserAttributes: [{ Name: "email", Value: email.trim().toLowerCase() }] });
    },
    confirm: async (email, code) => {
      await cognito("ConfirmSignUp", { Username: email.trim().toLowerCase(), ConfirmationCode: code.trim() });
    },
    resend: async (email) => {
      await cognito("ResendConfirmationCode", { Username: email.trim().toLowerCase() });
    },
    forgot: async (email) => {
      await cognito("ForgotPassword", { Username: email.trim().toLowerCase() });
    },
    resetPassword: async (email, code, password) => {
      await cognito("ConfirmForgotPassword", { Username: email.trim().toLowerCase(), ConfirmationCode: code.trim(), Password: password });
    },
    signOut: () => {
      store(null);
      setUser(null);
    },
  }), [user, ready, dialog, signIn]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Ctx {
  const c = useContext(AuthContext);
  if (!c) throw new Error("AuthProvider missing");
  return c;
}
