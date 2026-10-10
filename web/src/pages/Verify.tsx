import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Download, FileUp, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorNote, Spinner } from "../components/bits";
import { api } from "../lib/api";
import { dateTime } from "../lib/format";
import { useT } from "../lib/i18n";
import type { VerifyResult } from "../lib/types";

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function sha256Hex(data: ArrayBuffer | Uint8Array): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", data as BufferSource);
  return Array.from(new Uint8Array(d)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function pemFromSpki(spki: string): string {
  return `-----BEGIN PUBLIC KEY-----\n${spki.match(/.{1,64}/g)?.join("\n")}\n-----END PUBLIC KEY-----\n`;
}

type SigState = { state: "checking" } | { state: "nocrypto" } | { state: "done"; ok: boolean; keyOk: boolean; signed: VerifyResult["attestation"] | null };
type PdfState = { state: "idle" } | { state: "hashing" } | { state: "done"; match: boolean; hash: string; name: string } | { state: "error"; msg: string };

function Verdict({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <div className={`flex items-start gap-3 border-l-[5px] py-1 pl-4 ${ok ? "border-live" : "border-built"}`}>
      {ok ? <CheckCircle2 size={26} className="mt-1 shrink-0 text-live" /> : <XCircle size={26} className="mt-1 shrink-0 text-built" />}
      <div>{children}</div>
    </div>
  );
}

export default function Verify() {
  const { id } = useParams();
  const { t, lang } = useT();
  const { data: v, isLoading, error } = useQuery({ queryKey: ["verify", id], enabled: !!id, queryFn: () => api.get<VerifyResult>(`/v1/verify/${id}`), retry: 0 });
  const [sig, setSig] = useState<SigState>({ state: "checking" });
  const [pdf, setPdf] = useState<PdfState>({ state: "idle" });
  const [drag, setDrag] = useState(false);

  useEffect(() => {
    if (!v) return;
    if (!window.isSecureContext || !window.crypto?.subtle) { setSig({ state: "nocrypto" }); return; }
    (async () => {
      try {
        const spki = b64ToBytes(v.publicKey.spki);
        const key = await crypto.subtle.importKey("spki", spki as BufferSource, { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
        const ok = await crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key, b64ToBytes(v.signature.raw) as BufferSource,
          new TextEncoder().encode(v.attestationCanonical));
        let signed: VerifyResult["attestation"] | null = null;
        try { signed = JSON.parse(v.attestationCanonical); } catch { signed = null; }
        const fp = (await sha256Hex(spki)).slice(0, 32);
        const sameId = !!signed && (signed.dossierId ?? signed.reportId) === id;
        const keyOk = sameId && fp === signed!.keyFingerprint && fp === v.publicKey.fingerprint;
        setSig({ state: "done", ok: ok && sameId, keyOk, signed });
      } catch {
        setSig({ state: "done", ok: false, keyOk: false, signed: null });
      }
    })();
  }, [v, id]);

  const signedPdfHash = sig.state === "done" ? sig.signed?.pdfSha256 : v?.attestation.pdfSha256;

  async function checkBytes(buf: ArrayBuffer, name: string) {
    if (!window.crypto?.subtle) return;
    setPdf({ state: "hashing" });
    const hash = await sha256Hex(buf);
    setPdf({ state: "done", match: hash === signedPdfHash, hash, name });
  }
  async function onFile(f?: File | null) {
    if (!f) return;
    try { await checkBytes(await f.arrayBuffer(), f.name); } catch (e: any) { setPdf({ state: "error", msg: e.message }); }
  }
  async function fetchPublished() {
    if (!v?.pdfUrl) return;
    setPdf({ state: "hashing" });
    try {
      const r = await fetch(v.pdfUrl, { cache: "no-store" });
      if (!r.ok) throw new Error(`${r.status}`);
      await checkBytes(await r.arrayBuffer(), v.pdfUrl.split("/").pop() ?? "signed.pdf");
    } catch (e: any) {
      setPdf({ state: "error", msg: e.message });
    }
  }

  const files = useMemo(() => {
    if (!v) return null;
    const mk = (data: BlobPart, type: string) => URL.createObjectURL(new Blob([data], { type }));
    return {
      att: mk(v.attestationCanonical, "application/json"),
      sig: mk(b64ToBytes(v.signature.der) as BlobPart, "application/octet-stream"),
      key: mk(pemFromSpki(v.publicKey.spki), "application/x-pem-file"),
    };
  }, [v]);
  useEffect(() => () => { if (files) Object.values(files).forEach((u) => URL.revokeObjectURL(u)); }, [files]);

  if (isLoading) return <div className="mx-auto max-w-[1400px] px-6 py-16"><Spinner label={t("common.loading")} /></div>;
  if (error || !v) return <div className="mx-auto max-w-[1400px] px-6 py-16"><ErrorNote>{t("verify.notFound")}</ErrorNote></div>;
  const s = sig.state === "done" ? sig.signed : null;
  const isReport = v.kind === "report";
  const sid = v.dossierId ?? v.reportId ?? id ?? "";
  const placeLink = isReport && v.lat != null && v.lon != null
    ? `/place?lat=${v.lat.toFixed(5)}&lon=${v.lon.toFixed(5)}${v.subject ? `&label=${encodeURIComponent(v.subject)}` : ""}` : null;

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6">
      <p className="muted text-[15px]">{isReport ? t("verify.titleReport") : t("verify.title")}</p>
      <h1 className="mt-1 max-w-[24ch] text-[clamp(2.1rem,4.6vw,3.4rem)]">
        {isReport ? t("verify.reportFor", { place: v.subject ?? `${v.lat} N, ${v.lon} E` }) : t("dossier.for", { lake: v.lakeName ?? v.lakeId ?? "" })}
      </h1>
      <p className="mt-3 max-w-prose text-[16px] text-ink-2">{t("verify.lede")}</p>

      <div className="mt-10 grid gap-12 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] [&>*]:min-w-0">
        <div className="min-w-0 space-y-9">
          <section aria-live="polite">
            {sig.state === "checking" && <Spinner label={t("verify.checking")} />}
            {sig.state === "nocrypto" && (
              <Verdict ok={v.serverCheck}><p className="text-[17px]">{t("verify.noCrypto", { result: v.serverCheck ? t("verify.valid") : t("verify.invalid") })}</p></Verdict>
            )}
            {sig.state === "done" && (
              <Verdict ok={sig.ok}>
                <p className="display text-[clamp(1.7rem,3vw,2.3rem)]">{sig.ok ? t("verify.sigOk") : t("verify.sigBad")}</p>
                <p className={`mt-1 text-[15.5px] ${sig.keyOk ? "text-ink-2" : "text-built"}`}>{sig.keyOk ? t("verify.keyMatch") : t("verify.keyMismatch")}</p>
                {s?.signedAt && <p className="muted text-[15px]">{t("verify.signedAt", { date: dateTime(s.signedAt, lang) })}</p>}
              </Verdict>
            )}
            {v.publicKey.local && <p className="mt-3 rounded-md bg-lost/10 px-3 py-2 text-[14.5px]">{t("verify.local")}</p>}
          </section>

          <section>
            <label
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); onFile(e.dataTransfer.files?.[0]); }}
              className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${drag ? "border-memory bg-memory/5" : "border-line bg-paper-2 hover:border-memory"}`}>
              <FileUp size={26} className="text-ink-2" />
              <span className="text-[16px] font-semibold">{t("verify.drop")}</span>
              <input type="file" accept="application/pdf,.pdf" className="sr-only" onChange={(e) => onFile(e.target.files?.[0])} />
            </label>
            {v.pdfUrl && <button className="btn-quiet mt-3" onClick={fetchPublished} disabled={pdf.state === "hashing"}>{t("verify.fetchPdf")}</button>}
            <div className="mt-4" aria-live="polite">
              {pdf.state === "hashing" && <Spinner label={t("verify.checkingPdf")} />}
              {pdf.state === "done" && (
                <Verdict ok={pdf.match}>
                  <p className="text-[17px] font-semibold">{pdf.match ? t("verify.match") : t("verify.mismatch")}</p>
                  <p className="muted text-[13.5px]">{pdf.name}</p>
                  <p className="num break-all text-[12.5px] text-ink-2">{pdf.hash}</p>
                </Verdict>
              )}
              {pdf.state === "error" && <ErrorNote>{t("common.error", { msg: pdf.msg })}</ErrorNote>}
            </div>
          </section>

          {v.ledger ? (
            <section>
              <Verdict ok={v.ledger.ok}>
                <p className="text-[16.5px]">{v.ledger.ok ? t("verify.chainOk", { n: v.ledger.entries }) : t("verify.chainBad", { n: v.ledger.brokenAt ?? "?" })}</p>
                <p className="muted text-[15px]">{t("verify.status", { status: t(`dossier.status.${v.status}` as any) })}</p>
              </Verdict>
              <div className="mt-4 flex flex-wrap gap-2">
                <Link className="btn-primary" to={`/dossier/${v.dossierId}`}>{t("verify.openDossier")}</Link>
                <Link className="btn-ghost" to={`/lake/${v.lakeId}`}>{v.lakeName ?? v.lakeId}</Link>
              </div>
            </section>
          ) : (
            <section>
              <p className="muted text-[15px]">{t("verify.reportMade", { date: dateTime(v.createdAt, lang) })}</p>
              {placeLink && <Link className="btn-primary mt-4" to={placeLink}>{t("verify.openPlace")}</Link>}
            </section>
          )}
        </div>

        <aside className="min-w-0 space-y-9">
          <div>
            <h3>{t("verify.details")}</h3>
            <dl className="mt-3 space-y-3 text-[14px]">
              {([
                [isReport ? t("verify.reportId") : t("verify.dossierId"), s?.dossierId ?? s?.reportId ?? sid],
                [t("verify.payload"), s?.payloadSha256 ?? v.attestation.payloadSha256],
                [t("verify.pdf"), s?.pdfSha256 ?? v.attestation.pdfSha256],
                [t("verify.key"), s?.keyFingerprint ?? v.attestation.keyFingerprint],
              ] as const).map(([k, val]) => (
                <div key={k}><dt className="font-semibold">{k}</dt><dd className="num break-all text-ink-2">{val}</dd></div>
              ))}
            </dl>
          </div>
          <div>
            <h3>{t("verify.howTitle")}</h3>
            <p className="mt-2 text-[15px] leading-relaxed text-ink-2">{t(isReport ? "verify.howReport" : "verify.how")}</p>
            <pre className="mt-3 whitespace-pre-wrap break-all rounded-lg bg-paper-2 p-3 font-mono text-[12px] leading-relaxed">{v.attestationCanonical}</pre>
            {files && (
              <div className="mt-4">
                <div className="flex flex-wrap gap-2">
                  <a className="btn-quiet px-3 py-1.5 text-[14px]" href={files.att} download={`${sid}-attestation.json`}><Download size={15} /> attestation.json</a>
                  <a className="btn-quiet px-3 py-1.5 text-[14px]" href={files.sig} download={`${sid}-signature.der`}><Download size={15} /> signature.der</a>
                  <a className="btn-quiet px-3 py-1.5 text-[14px]" href={files.key} download="jalsmriti-public-key.pem"><Download size={15} /> {t("verify.publicKey")}</a>
                </div>
                <pre className="mt-3 overflow-x-auto rounded-lg bg-paper-2 p-3 font-mono text-[12px]">{`openssl dgst -sha256 -verify jalsmriti-public-key.pem \\\n  -signature ${sid}-signature.der ${sid}-attestation.json`}</pre>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
