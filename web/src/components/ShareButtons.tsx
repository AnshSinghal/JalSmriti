import { Check, Copy, MessageCircle } from "lucide-react";
import { useState } from "react";
import { useT } from "../lib/i18n";

/** WhatsApp is where neighbourhoods and residents' associations talk, so sharing goes there first; a plain link too. */
export default function ShareButtons({ text, path }: { text: string; path?: string }) {
  const { t } = useT();
  const [copied, setCopied] = useState(false);
  const url = path ? `${window.location.origin}${path}` : window.location.href;
  const wa = `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`;
  return (
    <>
      <a className="btn-quiet" href={wa} target="_blank" rel="noreferrer">
        <MessageCircle size={16} aria-hidden="true" /> {t("share.whatsapp")}
      </a>
      <button className="btn-quiet" onClick={() => { navigator.clipboard?.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1800); }}>
        {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />} {copied ? t("place.copied") : t("place.share")}
      </button>
    </>
  );
}
