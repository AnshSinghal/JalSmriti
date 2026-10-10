"""Evidence dossier PDF (fpdf2 with HarfBuzz shaping for Indic scripts, Nepali and Urdu).

The dossier carries: the satellite facts computed by code, a 1990-to-now time-lapse of the water body, the water
history chart, citizen evidence with provenance (capture time, GPS check, SHA-256, verification status), the
letter in English and in the chosen language, legal references, data sources and a verification block with the
content hash and a QR code that opens the public verify page.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

FONT_DIR = Path(__file__).resolve().parent / "fonts"
IST = timezone(timedelta(hours=5, minutes=30))

INK = (21, 30, 46)
MUTED = (88, 99, 115)
RULE = (214, 220, 228)
ACCENT = (14, 116, 144)       # deep teal
WARN = (194, 65, 12)
OK = (21, 128, 61)
PANEL = (240, 246, 248)

SCRIPTS = {  # lang -> (font family, OpenType script, language)
    "hi": ("NotoSansDevanagari", "deva", "hin"), "mr": ("NotoSansDevanagari", "deva", "mar"),
    "ne": ("NotoSansDevanagari", "deva", "nep"), "kn": ("NotoSansKannada", "knda", "kan"),
    "ta": ("NotoSansTamil", "taml", "tam"), "te": ("NotoSansTelugu", "telu", "tel"),
    "ml": ("NotoSansMalayalam", "mlym", "mal"), "bn": ("NotoSansBengali", "beng", "ben"),
    "as": ("NotoSansBengali", "beng", "asm"), "gu": ("NotoSansGujarati", "gujr", "guj"),
    "pa": ("NotoSansGurmukhi", "guru", "pan"), "or": ("NotoSansOriya", "orya", "ori"),
    "ur": ("NotoNaskhArabic", "arab", "urd"),
}
LANG_LABEL = {"hi": "हिन्दी", "mr": "मराठी", "ne": "नेपाली", "kn": "ಕನ್ನಡ", "ta": "தமிழ்", "te": "తెలుగు", "ml": "മലയാളം",
              "bn": "বাংলা", "as": "অসমীয়া", "gu": "ગુજરાતી", "pa": "ਪੰਜਾਬੀ", "or": "ଓଡ଼ିଆ", "ur": "اردو"}


def fmt_time(iso: str | None) -> str:
    if not iso:
        return "-"
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    d = d.astimezone(IST)
    return f"{d.day} {d.strftime('%b %Y, %H:%M')} IST"


class _Doc(FPDF):
    footer_text = ""

    def multi_cell(self, w, h=None, text="", *args, **kwargs):
        kwargs.setdefault("align", "L")          # never justify: hashes and IDs would be stretched
        return super().multi_cell(w, h, text, *args, **kwargs)

    def footer(self):
        self.set_y(-13)
        self.latin(7)
        self.set_text_color(*MUTED)
        self.multi_cell(self.w - self.l_margin - self.r_margin - 25, 3.3, self.footer_text, align="L",
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_xy(self.w - self.r_margin - 25, -10)
        self.cell(25, 3, f"Page {self.page_no()} of {{nb}}", align="R")

    def latin(self, size: float, bold: bool = False):
        self.set_text_shaping(False)
        self.set_font("NotoSans", "B" if bold else "", size)

    def script(self, lang: str, size: float, bold: bool = False):
        fam, sc, lg = SCRIPTS[lang]
        # switch away and back: after a run that ended in the fallback font, fpdf2 would otherwise skip the font
        # change and draw the next shaped glyphs with the wrong font
        self.set_text_shaping(False)
        self.set_font("NotoSans", "B" if bold else "", size)
        self.set_font(fam, "B" if bold else "", size)
        self.set_text_shaping(use_shaping_engine=True, script=sc, language=lg,
                              direction="rtl" if lang == "ur" else "ltr")


def _new_doc(langs: set[str]) -> _Doc:
    pdf = _Doc(orientation="P", unit="mm", format="A4")
    pdf.set_margins(15, 14, 15)
    pdf.set_auto_page_break(True, margin=18)
    fams = {"NotoSans"} | {SCRIPTS[l][0] for l in langs if l in SCRIPTS}
    for fam in fams:
        pdf.add_font(fam, "", str(FONT_DIR / f"{fam}-Regular.ttf"))
        pdf.add_font(fam, "B", str(FONT_DIR / f"{fam}-Bold.ttf"))
    pdf.set_fallback_fonts(["NotoSans"])
    return pdf


def _img(data: bytes, max_px: int = 720) -> io.BytesIO:
    """Any image (WebP with alpha included) -> JPEG on white, for embedding."""
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return buf


def _section(pdf: _Doc, title: str, lang: str | None = None):
    if pdf.get_y() > pdf.h - 40:
        pdf.add_page()
    pdf.ln(2.5)
    if lang and lang in SCRIPTS:
        pdf.script(lang, 10, True)
    else:
        pdf.latin(8.5, True)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 5.5, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(*RULE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(1.8)


def _kv(pdf: _Doc, rows: list[tuple[str, str]], w_label: float = 46):
    W = pdf.w - pdf.l_margin - pdf.r_margin
    for label, value in rows:
        y = pdf.get_y()
        pdf.latin(8.5)
        pdf.set_text_color(*MUTED)
        pdf.set_xy(pdf.l_margin, y)
        pdf.multi_cell(w_label, 4.5, label, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_xy(pdf.l_margin + w_label, y)
        pdf.latin(9.2)
        pdf.set_text_color(*INK)
        pdf.multi_cell(W - w_label, 4.5, value, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_y(max(pdf.get_y(), y + 5.0))


def _chart(pdf: _Doc, series: list[dict], hist_ha: float):
    """Bar chart of the post-monsoon water spread per season (code-drawn, no plotting library)."""
    if not series:
        return
    W = pdf.w - pdf.l_margin - pdf.r_margin
    H = 34
    x0, y0 = pdf.l_margin, pdf.get_y() + 2
    top = max(hist_ha, max(s["waterHa"] for s in series), 1.0)
    first, last = min(s["season"] for s in series), max(s["season"] for s in series)
    n = last - first + 1
    bw = W / max(n, 1)
    pdf.set_draw_color(*RULE)
    pdf.line(x0, y0 + H, x0 + W, y0 + H)
    yh = y0 + H - H * hist_ha / top
    pdf.set_dash_pattern(dash=1, gap=1)
    pdf.set_draw_color(*WARN)
    pdf.line(x0, yh, x0 + W, yh)
    pdf.set_dash_pattern()
    by = {s["season"]: s for s in series}
    for i in range(n):
        s = by.get(first + i)
        if not s:
            continue
        h = H * s["waterHa"] / top
        pdf.set_fill_color(*((52, 132, 238) if s.get("source") == "LS" else (14, 116, 144)))
        pdf.rect(x0 + i * bw + 0.3, y0 + H - h, max(bw - 0.6, 0.4), h, style="F")
    pdf.latin(6.5)
    pdf.set_text_color(*MUTED)
    for yr in range(first, last + 1, 5 if n > 20 else 2):
        pdf.set_xy(x0 + (yr - first) * bw - 3, y0 + H + 0.8)
        pdf.cell(8, 3, str(yr), align="C")
    pdf.set_xy(x0, y0 + H + 4.2)
    pdf.set_text_color(*WARN)
    pdf.cell(W, 3, f"Dashed line: historic spread, {hist_ha:g} ha (1984-2020)", align="L")
    pdf.set_y(y0 + H + 9)


def render(d: dict, crops: list[tuple[str, bytes]], evidence_imgs: list[tuple[dict, bytes]], qr_png: bytes | None,
           verify_url: str) -> bytes:
    """d: the dossier record (facts, letter, translation, evidence, hashes)."""
    lang = d.get("language", "hi")
    langs = {lang} if lang in SCRIPTS else set()
    pdf = _new_doc(langs)
    f = d["facts"]
    pdf.footer_text = ("JalSmriti evidence dossier. Satellite facts are computed by code from open data (Landsat, "
                       "Sentinel-1/2, JRC Global Surface Water, Impact Observatory land cover, NASA POWER rainfall). A "
                       "decision aid for citizens and authorities, not a cadastral survey; boundaries are approximate.")
    pdf.alias_nb_pages()
    pdf.add_page()
    W = pdf.w - pdf.l_margin - pdf.r_margin

    # ---- header band
    pdf.set_fill_color(*PANEL)
    pdf.rect(0, 0, pdf.w, 25, style="F")
    pdf.set_xy(pdf.l_margin, 7)
    pdf.latin(8, True)
    pdf.set_text_color(*ACCENT)
    pdf.cell(W * 0.62, 4, "JalSmriti water-body evidence dossier")
    pdf.set_text_color(*INK)
    pdf.latin(10.5, True)
    pdf.cell(W * 0.38, 4, d["dossierId"].upper(), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1.2)
    pdf.latin(8.2)
    pdf.set_text_color(*MUTED)
    pdf.cell(W * 0.62, 4, ", ".join(x for x in (f.get("areaName") or f.get("state"), f"prepared {fmt_time(d.get('createdAt'))}") if x))
    pdf.set_text_color(*OK)
    pdf.latin(8, True)
    pdf.cell(W * 0.38, 4, "Digitally signed: see the last page", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_y(29)

    # ---- title and recipient
    pdf.set_text_color(*INK)
    pdf.latin(15, True)
    pdf.multi_cell(W, 7, f["lakeName"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.latin(8.8)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(W, 4.4, f"{f['lat']:.5f} N, {f['lon']:.5f} E, JalSmriti lake id {f['lakeId']}. "
                           f"Addressed to {d.get('recipient', {}).get('name', '-')}.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ---- facts
    _section(pdf, "What the satellite record shows (computed by code)")
    rows = [("Historic water spread", f"{f['historicHa']:g} ha seen as water at least 5% of the time, 1984-2020"),
            ("Water lost since 1984", f"{f['lostHa']:g} ha ({f.get('lostPct', 0):g}% of the historic spread)")]
    if f.get("builtHa") is not None:
        rows.append(("Built over (old lake bed)", f"{f['builtHa']:g} ha ({f.get('builtPct', 0):g}%), Impact Observatory 10 m land cover {f.get('builtYear', '')}"))
    if f.get("retentionPct") is not None:
        rows.append(("Water held recently", f"{f['retentionPct']}% of what it held in past years of similar monsoon rain"))
    if f.get("weedPct") is not None:
        rows.append(("Floating weeds", f"{f['weedPct']:g}% of the water surface on {f.get('qualityDate')}"))
    if f.get("storageLowML"):
        rows.append(("Lost storage (estimate)", f"{f['storageLowML']:,}-{f['storageHighML']:,} million litres if 1-2 m deep"))
    rows.append(("Health grade", f"{f.get('grade') or '-'} ({f.get('score') or '-'}/100)"))
    n_ev, n_ok = f.get("evidenceCount", 0), f.get("verifiedCount", 0)
    rows.append(("Citizen evidence", f"{n_ev} {'photo' if n_ev == 1 else 'photos'}, {n_ok} verified by an NGO verifier"))
    _kv(pdf, rows)

    # ---- time-lapse
    if crops:
        _section(pdf, "Time-lapse in true colour; the yellow line is the historic outline")
        n = min(len(crops), 6)
        gap = 2.5
        cw = (W - gap * (n - 1)) / n
        y = pdf.get_y()
        for i, (label, data) in enumerate(crops[:n]):
            x = pdf.l_margin + i * (cw + gap)
            pdf.image(_img(data, 420), x=x, y=y, w=cw, h=cw)
            pdf.set_draw_color(*RULE)
            pdf.rect(x, y, cw, cw)
            pdf.set_xy(x, y + cw + 0.8)
            pdf.latin(7)
            pdf.set_text_color(*MUTED)
            pdf.cell(cw, 3, label, align="C")
        pdf.set_y(y + cw + 5)

    # ---- chart
    if f.get("series"):
        _section(pdf, "Water spread after each monsoon (ha): blue Landsat, teal Sentinel-2")
        _chart(pdf, f["series"], f["historicHa"])

    # ---- evidence
    if evidence_imgs:
        _section(pdf, "Citizen evidence: faces blurred, originals kept unchanged with their SHA-256")
        cols, gap = 3, 3
        cw = (W - gap * (cols - 1)) / cols
        for idx, (ev, data) in enumerate(evidence_imgs[:6]):
            col = idx % cols
            if col == 0:
                if pdf.get_y() > pdf.h - 75:
                    pdf.add_page()
                row_y = pdf.get_y()
            x = pdf.l_margin + col * (cw + gap)
            ih = cw * 0.66
            pdf.image(_img(data, 520), x=x, y=row_y, w=cw, h=ih, keep_aspect_ratio=True)
            pdf.set_xy(x, row_y + ih + 0.8)
            pdf.latin(6.6)
            pdf.set_text_color(*INK)
            gps_text = {"inside": "GPS: taken at the lake", "near": "GPS: taken near the lake",
                        "far": "GPS: taken far from the lake"}.get(ev.get("gpsCheck") or "", "no GPS in photo")
            cap = [f"{(ev.get('capturedAt') or ev.get('createdAt') or '')[:10]}, {', '.join(ev.get('categories') or []) or 'photo'}",
                   gps_text,
                   f"status: {ev.get('status', 'new')}   sha256 {ev.get('sha256', '')[:16]}…"]
            pdf.multi_cell(cw, 3, "\n".join(cap), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if col == cols - 1 or idx == min(len(evidence_imgs), 6) - 1:
                pdf.set_y(row_y + ih + 12)

    # ---- letter in English
    letter = d["letter"]
    _section(pdf, "Letter in English")
    pdf.latin(9.6, True)
    pdf.set_text_color(*INK)
    pdf.multi_cell(W, 5, letter["subject"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.latin(9.4)
    pdf.multi_cell(W, 4.9, letter["body"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if letter.get("asks"):
        pdf.ln(1)
        pdf.latin(9, True)
        pdf.cell(W, 5, "Actions requested", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.latin(9.2)
        for i, a in enumerate(letter["asks"], 1):
            pdf.multi_cell(W, 4.8, f"{i}.  {a}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ---- letter in the chosen language
    tr = d.get("translation")
    if tr and lang in SCRIPTS and tr.get("body"):
        _section(pdf, f"{LANG_LABEL.get(lang, lang)}", lang=lang)
        pdf.script(lang, 10.2, True)
        pdf.set_text_color(*INK)
        pdf.multi_cell(W, 6, tr["subject"], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R" if lang == "ur" else "L")
        pdf.script(lang, 9.8)
        pdf.multi_cell(W, 6, tr["body"], new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R" if lang == "ur" else "L")
        if tr.get("asks"):
            for i, a in enumerate(tr["asks"], 1):
                pdf.script(lang, 9.6)
                pdf.multi_cell(W, 5.8, f"{i}.  {a}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R" if lang == "ur" else "L")
        pdf.latin(7)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(W, 3.4, f"Machine translation by {tr.get('engine')}; every number checked against the English.",
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ---- references and sources
    _section(pdf, "Legal references and data sources")
    pdf.latin(8.2)
    pdf.set_text_color(*INK)
    for law in f.get("laws", []):
        pdf.multi_cell(W, 4.2, f"•  {law}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(W, 4, "Data: JRC Global Surface Water v1.3 (1984-2020); USGS Landsat 4-9 Collection 2 and Copernicus "
                         "Sentinel-2 L2A (via Microsoft Planetary Computer and Earth Search on AWS Open Data); Copernicus "
                         "Sentinel-1 RTC; Impact Observatory 10 m annual land cover; ESA WorldCover 2021; NASA POWER rainfall; "
                         "Copernicus GLO-30 elevation. Names: OpenStreetMap contributors, GeoNames.",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ---- verification
    if pdf.get_y() > pdf.h - 60:
        pdf.add_page()
    _section(pdf, "Verification")
    y = pdf.get_y()
    if qr_png:
        pdf.image(io.BytesIO(qr_png), x=pdf.w - pdf.r_margin - 30, y=y, w=30, h=30)
    pdf.set_xy(pdf.l_margin, y)
    tw = W - 36

    def pair(label, value, mono=True):
        pdf.latin(7.6)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(tw, 3.6, label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*INK)
        if mono:
            pdf.set_text_shaping(False)
            pdf.set_font("Courier", "", 7.4)
        else:
            pdf.latin(8.4)
        pdf.multi_cell(tw, 3.8, value, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(0.8)

    pair("Content SHA-256 (facts, letter, evidence hashes, frames)", d.get("payloadSha256", ""))
    pair(f"Lake record chain head (entry {d.get('ledger', {}).get('seq', 0)})", d.get("ledger", {}).get("hash", ""))
    pair("Signing key (ECDSA P-256 in AWS KMS) fingerprint", d.get("keyFingerprint", ""))
    pair("Check this document", verify_url, mono=False)
    pdf.latin(7.6)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(tw, 3.6, "Open that page and drop this PDF on it: your browser computes the file's SHA-256 and checks "
                            "the KMS signature itself. Any change to the PDF changes the hash.",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_y(max(pdf.get_y(), y + 32))
    return bytes(pdf.output())
