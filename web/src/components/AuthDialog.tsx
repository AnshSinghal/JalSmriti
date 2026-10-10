import * as Dialog from "@radix-ui/react-dialog";
import { Loader2, X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useAuth } from "../lib/auth";
import { useT } from "../lib/i18n";

type Mode = "signin" | "signup" | "confirm" | "forgot" | "reset";

export default function AuthDialog() {
  const { dialog, closeAuth, signIn, signUp, confirm, resend, forgot, resetPassword } = useAuth();
  const { t } = useT();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (dialog) {
      setMode(dialog.mode);
      setError(null);
      setNote(null);
    }
  }, [dialog]);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e: any) {
      if (e?.code === "UserNotConfirmedException") {
        setMode("confirm");
        setNote(t("auth.sent", { email }));
      } else setError(e?.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (mode === "signin") run(async () => { await signIn(email, password); closeAuth(); });
    if (mode === "signup") run(async () => { await signUp(email, password); setMode("confirm"); setNote(t("auth.sent", { email })); });
    if (mode === "confirm") run(async () => { await confirm(email, code); await signIn(email, password); closeAuth(); });
    if (mode === "forgot") run(async () => { await forgot(email); setMode("reset"); setNote(t("auth.sent", { email })); });
    if (mode === "reset") run(async () => { await resetPassword(email, code, password); await signIn(email, password); closeAuth(); });
  }

  const title = { signin: t("auth.signin"), signup: t("auth.signup"), confirm: t("auth.confirm"), forgot: t("auth.forgot"), reset: t("auth.reset") }[mode];
  return (
    <Dialog.Root open={!!dialog} onOpenChange={(o) => !o && closeAuth()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-[rgb(6_12_24/0.55)] backdrop-blur-[2px]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,420px)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line bg-paper p-6 shadow-2xl">
          <div className="flex items-start justify-between gap-4">
            <Dialog.Title className="display text-[1.8rem]">{title}</Dialog.Title>
            <Dialog.Close className="btn-ghost -mr-2 -mt-1" aria-label={t("common.close")}><X size={18} /></Dialog.Close>
          </div>
          <Dialog.Description className="muted mt-1 text-[15px]">{dialog?.reason ?? t("auth.why")}</Dialog.Description>
          <form className="mt-5 space-y-3.5" onSubmit={submit}>
            <div>
              <label className="label" htmlFor="auth-email">{t("auth.email")}</label>
              <input id="auth-email" className="field" type="email" autoComplete="email" required value={email}
                onChange={(e) => setEmail(e.target.value)} disabled={mode === "confirm" || mode === "reset"} />
            </div>
            {(mode === "confirm" || mode === "reset") && (
              <div>
                <label className="label" htmlFor="auth-code">{t("auth.code")}</label>
                <input id="auth-code" className="field tracking-widest" inputMode="numeric" autoComplete="one-time-code" required value={code}
                  onChange={(e) => setCode(e.target.value)} />
              </div>
            )}
            {mode !== "confirm" && mode !== "forgot" && (
              <div>
                <label className="label" htmlFor="auth-password">{mode === "reset" ? t("auth.newPassword") : t("auth.password")}</label>
                <input id="auth-password" className="field" type="password" required minLength={mode === "signin" ? 1 : 10}
                  autoComplete={mode === "signin" ? "current-password" : "new-password"} value={password}
                  onChange={(e) => setPassword(e.target.value)} />
                {(mode === "signup" || mode === "reset") && <p className="muted mt-1 text-[13.5px]">{t("auth.passwordRule")}</p>}
              </div>
            )}
            {note && <p className="rounded-md bg-memory-soft/60 px-3 py-2 text-[14.5px]">{note}</p>}
            {error && <p role="alert" className="rounded-md bg-built/10 px-3 py-2 text-[14.5px] text-built">{error}</p>}
            <button className="btn-primary w-full" disabled={busy}>
              {busy && <Loader2 size={16} className="animate-spin" />} {title}
            </button>
          </form>
          <div className="mt-4 flex flex-wrap justify-between gap-2 text-[14.5px]">
            {mode === "signin" && <>
              <button className="link tap" onClick={() => setMode("signup")}>{t("auth.noAccount")}</button>
              <button className="link tap" onClick={() => setMode("forgot")}>{t("auth.forgot")}</button>
            </>}
            {mode === "signup" && <button className="link tap" onClick={() => setMode("signin")}>{t("auth.haveAccount")}</button>}
            {mode === "confirm" && <button className="link tap" onClick={() => run(() => resend(email))}>{t("auth.resend")}</button>}
            {(mode === "forgot" || mode === "reset") && <button className="link tap" onClick={() => setMode("signin")}>{t("auth.haveAccount")}</button>}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
