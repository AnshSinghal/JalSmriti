"""Signed place report PDF: what a place remembers about water, for a family about to rent or buy a home.

One or two A4 pages: the water-memory gauge and what the records show, the satellite time-lapse, monsoon radar
sightings, summer heat, standing water reported by people nearby, this week's checklist, questions for the owner or
seller, the limits of the method and a verification block (content hash, signing key fingerprint, QR code to the
public verify page).

Every string arrives already translated (en, hi, kn, ta, te, ml, ne); this module only lays it out, with the pieces of
the evidence dossier renderer (pdf.py): text in an Indian script is set in the matching Noto font and shaped with
HarfBuzz (Latin letters inside it fall back to Noto Sans), text without such letters (ids, numbers, coordinates) is set
in Noto Sans, hashes in Courier. render() lays the report out at up to three densities and keeps the most comfortable
one that does not end on a nearly empty page, so typical content fills two pages in every language.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from fpdf.enums import MethodReturnValue, XPos, YPos

from .pdf import ACCENT, INK, MUTED, OK, PANEL, RULE, SCRIPTS, _Doc, _img, _new_doc

__all__ = ["render"]

PT = 25.4 / 72                    # mm per point
WHITE = (255, 255, 255)
# the website's survey-paper palette (web/src/styles/index.css); red and amber only ever mean loss
BUILT = (210, 58, 53)             # old water bed now built over
LOST = (217, 144, 26)             # water that has gone
MEMORY = (31, 79, 153)            # remembered water
PAPER2 = (232, 238, 236)
TIER_COLOR = {"strong": BUILT, "some": LOST, "little": MEMORY}
LEVEL_COLOR = {"avoid": BUILT, "think": LOST, "checks": MEMORY, "fine": (46, 125, 72)}
SEVERITY_COLOR = {"high": BUILT, "medium": LOST}
HEAT_RAMP = ("#313695", "#74add1", "#fee090", "#f46d43", "#a50026")
# alias for the page count: one character, so fpdf2 reserves the width of one digit and right-aligned page labels
# stay flush with the margin (the default "{nb}" reserves three)
TOTAL_ALIAS = "\ue000"            # a private-use character, never in real text
MIN_LAST_PAGE_FILL = 0.3          # a last page filled less than this is "nearly empty"
MAX_GAP = 45.0                    # empty space (mm) a whole block may leave at the foot of a page before a denser
                                  # layout is preferred
FOOT_RIGHT = 34.0                 # width of the footer's page label column (mm)
HEAT_MIN = 38.0                   # the heat picture may shrink to this side (mm) to fit the room left on a page

DEFAULT_LABELS = {                # used only when the caller leaves a label out
    "docTitle": "JalSmriti place report", "signedNote": "Digitally signed: see the last page", "checked": "",
    "made": "", "coords": "", "memoryTitle": "What this place remembers", "findings": "What the records show",
    "timelapse": "The same spot through the years", "radar": "Monsoon radar sightings", "heat": "Summer heat",
    "reports": "Standing water reported nearby", "actions": "What you can do", "questions": "Questions to ask",
    "limits": "What this report cannot tell you", "verification": "Verification",
    "payload": "Content fingerprint (SHA-256)", "key": "Signing key fingerprint", "check": "Check this report",
    "checkHow": "", "footer": "", "page": "Page {n} of {total}",
}

# Unicode blocks of the scripts pdf.py has fonts for, by OpenType script tag
_BLOCKS = (("deva", 0x0900, 0x097F), ("beng", 0x0980, 0x09FF), ("guru", 0x0A00, 0x0A7F), ("gujr", 0x0A80, 0x0AFF),
           ("orya", 0x0B00, 0x0B7F), ("taml", 0x0B80, 0x0BFF), ("telu", 0x0C00, 0x0C7F), ("knda", 0x0C80, 0x0CFF),
           ("mlym", 0x0D00, 0x0D7F), ("arab", 0x0600, 0x06FF))
# line height per script, in multiples of the font size: Kannada and Telugu stack conjuncts deep below the line
_LEAD = {None: 1.42, "deva": 1.62, "beng": 1.62, "guru": 1.6, "gujr": 1.6, "orya": 1.62, "taml": 1.56, "telu": 1.7,
         "knda": 1.7, "mlym": 1.6, "arab": 1.75}


@dataclass(frozen=True)
class _Style:
    """One density of the layout (sizes in pt, lengths in mm)."""
    body: float = 9.4       # findings, checklist, questions
    small: float = 8.5      # explanations, limits, notes
    tiny: float = 7.1       # captions, tags, sources, verification labels
    head: float = 10.3      # section headings
    title: float = 16.5     # the place
    tier: float = 18.0      # the water-memory tier
    gap: float = 4.0        # space above a section heading
    item: float = 1.3       # space between list items
    heat: float = 55.0      # side of the heat image when the page has room for it
    gauge: float = 36.0     # least height of the staff gauge
    lead: float = 0.98      # line-height multiplier


_STYLES = (
    _Style(),
    _Style(body=9.0, small=8.2, tiny=6.9, head=9.9, title=15.5, tier=16.5, gap=3.4, item=1.0, heat=48.0, gauge=33.0,
           lead=0.95),
    _Style(body=8.6, small=7.8, tiny=6.7, head=9.5, title=15.0, tier=15.5, gap=2.8, item=0.7, heat=42.0, gauge=30.0,
           lead=0.92),
)


def _s(v) -> str:
    """Any value as trimmed text ('' for None), so odd input never stops the report."""
    return "" if v is None else (v if isinstance(v, str) else str(v)).strip()


def _texts(v) -> list[str]:
    """A list of strings without the empty ones."""
    return [t for t in (_s(x) for x in (v if isinstance(v, (list, tuple)) else [])) if t]


# ------------------------------------------------------------------------------------------------ fonts and text

def _script_of(text: str) -> str | None:
    for ch in text:
        o = ord(ch)
        if o >= 0x0600:
            for sc, lo, hi in _BLOCKS:
                if lo <= o <= hi:
                    return sc
    return None


def _lang_for(text: str, lang: str) -> str | None:
    """The pdf.SCRIPTS key whose font sets `text`: the reader's language when its script matches, else the first
    language written in that script (a place name in another script still gets the right font); None for text without
    Indian or Arabic letters, which Noto Sans sets."""
    sc = _script_of(text)
    if sc is None:
        return None
    if lang in SCRIPTS and SCRIPTS[lang][1] == sc:
        return lang
    return next(lg for lg, (_, s, _) in SCRIPTS.items() if s == sc)


def _strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _strings(x)


class _ReportDoc(_Doc):
    """pdf.py's document (fonts, margins, latin() and script()) with the report's localized footer."""
    st = _STYLES[0]
    reader = "en"
    page_label = DEFAULT_LABELS["page"]
    report_id = ""
    foot_size = 6.6
    foot_h = 6.0
    mcache: dict                     # measured text heights, per layout
    gaps: list                       # space left empty at the foot of pages broken before whole blocks

    def footer(self):
        with self.local_context():
            W, rw = self.epw, FOOT_RIGHT
            top = self.h - 8.0 - self.foot_h
            self.set_draw_color(*RULE)
            self.set_line_width(0.2)
            self.line(self.l_margin, top - 2.2, self.l_margin + W, top - 2.2)
            if self.footer_text:
                self.set_xy(self.l_margin, top)
                _write(self, self.footer_text, self.l_margin, W - rw - 6, self.foot_size, color=MUTED)
            label = self.page_label.replace("{n}", str(self.page_no())).replace("{total}", TOTAL_ALIAS)
            lh = _lh(self, _script_of(label), self.foot_size)
            size = _fit(self, label, rw, self.foot_size, False, 5.0)
            _label(self, label, self.l_margin + W - rw, top, rw, lh, size, color=MUTED, align="R")
            if self.report_id:
                size = _fit(self, self.report_id, rw, self.foot_size - 0.4, False, 4.5)
                _label(self, self.report_id, self.l_margin + W - rw, top + lh, rw, _lh(self, None, self.foot_size),
                       size, color=MUTED, align="R")


def _font(pdf: _ReportDoc, text: str, size: float, bold: bool = False) -> str | None:
    """Select the face for `text`; returns its script tag (None for Noto Sans)."""
    lg = _lang_for(text, pdf.reader)
    if lg is None:
        pdf.latin(size, bold)
        return None
    pdf.script(lg, size, bold)
    return SCRIPTS[lg][1]


def _pin_font(pdf: _ReportDoc):
    """Write the selected font to the page before drawing text with it.

    Work-around for fpdf2 2.8.9: when a line starts with a word in the fallback font (Latin inside Indian text), fpdf2
    selects the paragraph font inside that line's q/Q wrapper yet records it as set for the page, so the next line is
    drawn at whatever size the page had before (seen as a footer whose second line came out at body size). text()
    writes the selection to the page itself; with no text it draws nothing."""
    if not pdf.current_font_is_set_on_page:
        pdf.text(pdf.x, pdf.y, "")


def _mono(pdf: _ReportDoc, size: float):
    pdf.set_text_shaping(False)
    pdf.set_font("Courier", "", size)


def _lh(pdf: _ReportDoc, script: str | None, size: float, display: bool = False) -> float:
    return size * PT * _LEAD.get(script, 1.6) * pdf.st.lead * (0.86 if display else 1.0)


def _measure(pdf: _ReportDoc, text: str, w: float, size: float, bold: bool = False,
             display: bool = False) -> tuple[float, float]:
    """(height, line height) of `text` wrapped to width w, shaped exactly as it will be drawn."""
    key = (text, round(w, 2), size, bold, display)
    if key not in pdf.mcache:
        lh = _lh(pdf, _font(pdf, text, size, bold), size, display)
        pdf.mcache[key] = (pdf.multi_cell(w, lh, text, dry_run=True, output=MethodReturnValue.HEIGHT), lh)
    return pdf.mcache[key]


def _write(pdf: _ReportDoc, text: str, x: float, w: float, size: float, bold: bool = False, color=INK,
           display: bool = False, align: str = "L", link: str | None = None) -> float:
    """Draw `text` wrapped to width w at (x, current y); leaves y under it and returns its height."""
    h, lh = _measure(pdf, text, w, size, bold, display)
    _font(pdf, text, size, bold)
    _pin_font(pdf)
    pdf.set_text_color(*color)
    pdf.set_x(x)
    pdf.multi_cell(w, lh, text, align=align, link=link, new_x=XPos.LEFT, new_y=YPos.NEXT)
    return h


def _label(pdf: _ReportDoc, text: str, x: float, y: float, w: float, h: float, size: float, bold: bool = False,
           color=INK, align: str = "L"):
    """One line of text in a box (page labels, tags, ids)."""
    _font(pdf, text, size, bold)
    _pin_font(pdf)
    pdf.set_text_color(*color)
    pdf.set_xy(x, y)
    pdf.cell(w, h, text, align=align)


def _fit(pdf: _ReportDoc, text: str, max_w: float, size: float, bold: bool, min_size: float) -> float:
    """The largest size, down to min_size, at which `text` fits on one line of max_w."""
    while size > min_size:
        _font(pdf, text, size, bold)
        if pdf.get_string_width(text) <= max_w:
            return size
        size = round(size - 0.3, 2)
    return min_size


def _width(pdf: _ReportDoc, text: str, size: float, bold: bool = False) -> float:
    _font(pdf, text, size, bold)
    return pdf.get_string_width(text)


# ------------------------------------------------------------------------------------------------ flow helpers

def _room(pdf: _ReportDoc) -> float:
    """Space left above the page break, less a hair so that a block measured to fit never trips fpdf2's own break."""
    return pdf.page_break_trigger - pdf.get_y() - 0.5


def _at_top(pdf: _ReportDoc) -> bool:
    return pdf.get_y() <= pdf.t_margin + 0.5


def _new_page(pdf: _ReportDoc):
    """Page break before a block that must stay whole; remembers the space it leaves empty at the foot."""
    pdf.gaps.append(pdf.page_break_trigger - pdf.get_y())
    pdf.add_page()


def _advance(pdf: _ReportDoc, gap: float, need: float):
    """Move down by `gap` before a block `need` mm tall, or start a new page if the block would not fit."""
    if gap + need > _room(pdf) and not _at_top(pdf):
        _new_page(pdf)
    elif gap and not _at_top(pdf):
        pdf.set_y(pdf.get_y() + gap)


def _heading(pdf: _ReportDoc, title: str, need: float = 0.0):
    """Section title with a hairline under it, kept on the same page as the first `need` mm of its content."""
    st, W = pdf.st, pdf.epw
    h, _ = _measure(pdf, title, W, st.head, True)
    _advance(pdf, st.gap, h + 2.4 + need)
    _write(pdf, title, pdf.l_margin, W, st.head, bold=True, color=ACCENT)
    y = pdf.get_y() + 0.5
    pdf.set_draw_color(*RULE)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, y, pdf.l_margin + W, y)
    pdf.set_y(y + 1.9)


def _mix(c: tuple, bg: tuple, a: float) -> tuple:
    return tuple(round(b + (x - b) * a) for x, b in zip(c, bg))


def _ramp(t: float) -> tuple:
    stops = [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in HEAT_RAMP]
    pos = max(0.0, min(1.0, t)) * (len(stops) - 1)
    i = min(int(pos), len(stops) - 2)
    return _mix(stops[i + 1], stops[i], pos - i)


def _num(v) -> str:
    return f"{float(v):.1f}".rstrip("0").rstrip(".")


# ------------------------------------------------------------------------------------------------ sections

def _header(pdf: _ReportDoc, d: dict, L: dict):
    W, x0 = pdf.epw, pdf.l_margin
    rid = pdf.report_id
    rid_w = (_width(pdf, rid, 10.5, True) + 0.6) if rid else 0.0
    w1 = W - rid_w - (6 if rid else 0)
    s1 = _fit(pdf, L["docTitle"], w1, 8.8, True, 7.4)
    h1 = max(_measure(pdf, L["docTitle"], w1, s1, True)[0], 5.0)
    # line 2: when it was made (left) and the signature note (right, green) share the line by their real widths,
    # smaller down to 7 pt if need be, and wrap only past that
    made, note = L["made"], L["signedNote"]
    s2 = 8.2
    while True:
        made_w = _width(pdf, made, s2) if made else 0.0
        # slack: multi_cell breaks shaped text a little earlier than get_string_width measures it; the note is
        # right-aligned, so the extra room does not show
        note_w = _width(pdf, note, s2, True) * 1.04 + 2.0 if note else 0.0
        if made_w + note_w + 6 <= W or s2 <= 7.0:
            break
        s2 = round(s2 - 0.3, 2)
    if made_w + note_w + 6 > W:
        note_w = min(note_w, max(W * 0.45, W - made_w - 6))
    w2 = W - note_w - (6 if note else 0)
    h2 = max(_measure(pdf, made, w2, s2)[0] if made else 0, _measure(pdf, note, note_w, s2, True)[0] if note else 0,
             4.6)
    y1, y2 = 6.0, 6.0 + h1 + 1.0
    band = y2 + h2 + 4.6
    pdf.set_fill_color(*PANEL)
    pdf.rect(0, 0, pdf.w, band, style="F")
    pdf.set_y(y1)
    _write(pdf, L["docTitle"], x0, w1, s1, bold=True, color=ACCENT)
    if rid:
        _label(pdf, rid, x0 + W - rid_w, y1, rid_w, h1, 10.5, bold=True, align="R")
    if made:
        pdf.set_y(y2)
        _write(pdf, made, x0, w2, s2, color=MUTED)
    if note:
        pdf.set_y(y2)
        _write(pdf, note, x0 + W - note_w, note_w, s2, bold=True, color=OK, align="R")
    pdf.set_y(band + 4.4)


def _title(pdf: _ReportDoc, d: dict, L: dict):
    st, W, x0 = pdf.st, pdf.epw, pdf.l_margin
    title = _s(d.get("title")) or L["coords"]
    if title:
        _write(pdf, title, x0, W, st.title, bold=True, display=True)
    sub = "   ·   ".join(s for s in (L["coords"], L["checked"]) if s and s != title)
    if sub:
        pdf.set_y(pdf.get_y() + 0.8)
        _write(pdf, sub, x0, W, st.small + 0.2, color=MUTED)


def _gauge(pdf: _ReportDoc, x: float, y: float, h: float, index, color: tuple):
    """Staff gauge like the website's MemoryGauge: a tall bar with a tick every 10 %, filled from the bottom to the
    index, with a level mark across it in the tier colour."""
    bar_x, bar_w = x + 4.6, 6.4
    top, bot = y + 0.8, y + h - 0.8
    bh = bot - top
    pdf.set_line_width(0.2)
    pdf.set_draw_color(*RULE)
    pdf.set_fill_color(*PAPER2)
    pdf.rect(bar_x, top, bar_w, bh, style="DF")
    pdf.set_draw_color(*MUTED)
    pdf.set_line_width(0.22)
    for i in range(11):
        ty = top + bh * i / 10
        pdf.line(x + (0.4 if i % 5 == 0 else 2.4), ty, bar_x, ty)
    if index is None:
        return
    fh = bh * max(0.0, min(100.0, float(index))) / 100
    if fh > 0.05:
        pdf.set_fill_color(*_mix(color, WHITE, 0.88))
        pdf.rect(bar_x, bot - fh, bar_w, fh, style="F")
    pdf.set_draw_color(*color)
    pdf.set_line_width(0.9)
    pdf.line(x + 2.4, bot - fh, bar_x + bar_w + 2.6, bot - fh)


def _memory(pdf: _ReportDoc, d: dict, L: dict):
    st, W, x0 = pdf.st, pdf.epw, pdf.l_margin
    tier = d.get("tier") if d.get("tier") in TIER_COLOR else "unknown"
    color = TIER_COLOR.get(tier, MUTED)
    index = d.get("index")
    index = index if isinstance(index, (int, float)) and not isinstance(index, bool) else None
    gw = 21.0
    tx, tw = x0 + gw, W - gw
    rows = [r for r in (                              # (gap above, text, size, bold, colour, display)
        (0.0, _s(d.get("tierLabel")), st.tier, True, color, True),
        (0.6, _s(d.get("indexLabel")) if index is not None else "", round(st.tier * 0.64, 1), True, MUTED, True),
        (2.6, _s(d.get("explain")), st.body, False, INK, False),
        (1.4, _s(d.get("validation")), st.small, False, MUTED, False),
    ) if r[1]]
    rows = [(g if i else 0.0, *r) for i, (g, *r) in enumerate(rows)]
    text_h = sum(g + _measure(pdf, t, tw, s, b, disp)[0] for g, t, s, b, _, disp in rows)
    H = max(text_h, st.gauge)
    _heading(pdf, L["memoryTitle"], need=H)
    y0 = pdf.get_y()
    _gauge(pdf, x0, y0, H, index, color)
    pdf.set_y(y0 + (H - text_h) / 2)
    for g, t, s, b, c, disp in rows:
        pdf.set_y(pdf.get_y() + g)
        _write(pdf, t, tx, tw, s, bold=b, color=c, display=disp)
    pdf.set_y(y0 + H)


def _verdict(pdf: _ReportDoc, d: dict, L: dict):
    """Our read for a family about to rent or buy: the level and headline on a panel edged in the level's colour,
    then why, what is in its favour (+) and against it (-), and the note that it is not a survey or advice."""
    v = d.get("verdict")
    if not isinstance(v, dict) or not _s(v.get("headline")):
        return
    st, W, x0 = pdf.st, pdf.epw, pdf.l_margin
    color = LEVEL_COLOR.get(v.get("level"), MUTED)
    pad, edge = 3.6, 1.4
    inner = W - 2 * pad - edge
    level, head = _s(v.get("levelLabel")), _s(v.get("headline"))
    lh_level = _measure(pdf, level, inner, st.body, True)[0] if level else 0.0
    lh_head = _measure(pdf, head, inner, st.body + 1.2, True)[0]
    panel = lh_level + (1.0 if level else 0.0) + lh_head + 2 * pad
    _heading(pdf, _s(v.get("title")) or "Our read", need=panel)
    y0 = pdf.get_y()
    pdf.set_fill_color(*_mix(color, WHITE, 0.10))
    pdf.rect(x0, y0, W, panel, style="F", round_corners=True, corner_radius=2.0)
    pdf.set_fill_color(*color)
    pdf.rect(x0, y0, edge, panel, style="F")
    pdf.set_y(y0 + pad)
    if level:
        _write(pdf, level, x0 + edge + pad, inner, st.body, bold=True, color=color)
        pdf.set_y(pdf.get_y() + 1.0)
    _write(pdf, head, x0 + edge + pad, inner, st.body + 1.2, bold=True)
    pdf.set_y(y0 + panel + 1.6)
    ind = 5.0
    tw = W - ind
    for title_key, items, mark, mcolor in (("whyTitle", v.get("why"), "", INK), ("prosTitle", v.get("pros"), "+", (46, 125, 72)),
                                           ("consTitle", v.get("cons"), "-", BUILT)):
        items = _texts(items)
        if not items:
            continue
        title = _s(v.get(title_key))
        if title:
            _advance(pdf, 1.4, _measure(pdf, title, W, st.small, True)[0] + _measure(pdf, items[0], tw, st.body)[0])
            _write(pdf, title, x0, W, st.small, bold=True, color=MUTED)
            pdf.set_y(pdf.get_y() + 0.6)
        for i, text in enumerate(items):
            h, lh = _measure(pdf, text, tw, st.body)
            _advance(pdf, st.item * 0.7 if i else 0.0, h)
            y = pdf.get_y()
            if mark:
                _label(pdf, mark, x0, y, ind, lh, st.body, bold=True, color=mcolor)
                pdf.set_y(y)
            else:
                pdf.set_fill_color(*MUTED)
                pdf.circle(x0 + 1.2, y + lh / 2, 0.6, style="F")
            _write(pdf, text, x0 + ind, tw, st.body)
    note = _s(v.get("note"))
    if note:
        _advance(pdf, 1.8, _measure(pdf, note, W, st.small)[0])
        _write(pdf, note, x0, W, st.small, color=MUTED)


def _findings(pdf: _ReportDoc, d: dict, L: dict):
    raw = d.get("findings") if isinstance(d.get("findings"), (list, tuple)) else []
    items = [(_s(f.get("text")), f.get("severity")) if isinstance(f, dict) else (_s(f), "info") for f in raw]
    items = [(t, s) for t, s in items if t]
    if not items:
        return
    st, x0 = pdf.st, pdf.l_margin
    ind = 5.6
    tw = pdf.epw - ind
    _heading(pdf, L["findings"], need=_measure(pdf, items[0][0], tw, st.body)[0])
    for i, (text, sev) in enumerate(items):
        h, lh = _measure(pdf, text, tw, st.body)
        _advance(pdf, st.item if i else 0.0, h)
        y, s = pdf.get_y(), 2.3
        pdf.set_fill_color(*SEVERITY_COLOR.get(sev, MUTED))
        pdf.rect(x0 + 0.2, y + lh / 2 - s / 2, s, s, style="F")
        _write(pdf, text, x0 + ind, tw, st.body)


def _timelapse(pdf: _ReportDoc, L: dict, frames: list[tuple[str, bytes]]):
    if not frames:
        return
    st, W, x0 = pdf.st, pdf.epw, pdf.l_margin
    gap = 2.4
    cw = (W - gap * 5) / 6                           # always the six-up size, so few frames do not balloon
    cap = max((_measure(pdf, lab, cw, st.tiny)[0] for lab, _ in frames if lab), default=0.0)
    block = cw + (1.2 + cap if cap else 0.0)
    _heading(pdf, L["timelapse"], need=block)
    y = pdf.get_y()
    for i, (label, jpg) in enumerate(frames):
        x = x0 + i * (cw + gap)
        pdf.image(io.BytesIO(jpg), x=x, y=y, w=cw, h=cw, keep_aspect_ratio=True)
        pdf.set_draw_color(*RULE)
        pdf.set_line_width(0.2)
        pdf.rect(x, y, cw, cw)
        if label:
            pdf.set_y(y + cw + 1.2)
            _write(pdf, label, x, cw, st.tiny, color=MUTED, align="C")
    pdf.set_y(y + block)


def _tags(pdf: _ReportDoc, items: list[str], draw: bool) -> float:
    """Dates as small rounded tags (the website's radar tags: built red on a light tint) that wrap; returns height."""
    st, W, x0 = pdf.st, pdf.epw, pdf.l_margin
    size, pad, gap = st.tiny + 0.5, 1.9, 1.6
    th = max(_lh(pdf, _script_of(t), size) for t in items) + 1.2
    x, y = x0, pdf.get_y()
    for t in items:
        tw = min(_width(pdf, t, size, True) + 2 * pad, W)
        if x > x0 and x + tw > x0 + W:
            x, y = x0, y + th + gap
        if draw:
            pdf.set_fill_color(*_mix(BUILT, WHITE, 0.1))
            pdf.rect(x, y, tw, th, style="F", round_corners=True, corner_radius=0.9)
            _label(pdf, t, x, y, tw, th, size, bold=True, color=BUILT, align="C")
        x += tw + gap
    if draw:
        pdf.set_y(y + th)
    return y + th - pdf.get_y()


def _radar(pdf: _ReportDoc, d: dict, L: dict):
    r = d.get("radar")
    if not isinstance(r, dict):
        return
    sentence, dates = _s(r.get("sentence")), _texts(r.get("dates"))
    if not sentence and not dates:
        return
    st, W, x0 = pdf.st, pdf.epw, pdf.l_margin
    hs = _measure(pdf, sentence, W, st.body)[0] if sentence else 0.0
    _heading(pdf, L["radar"], need=hs + (2.0 + _tags(pdf, dates, draw=False) if dates else 0.0))
    if sentence:
        _write(pdf, sentence, x0, W, st.body)
    if dates:
        if sentence:
            pdf.set_y(pdf.get_y() + 2.0)
        _tags(pdf, dates, draw=True)


def _colour_bar(pdf: _ReportDoc, x: float, y: float, w: float, h: float):
    n = max(24, int(w / 0.4))
    seg = w / n
    for i in range(n):
        pdf.set_fill_color(*_ramp((i + 0.5) / n))
        pdf.rect(x + i * seg, y, seg + (0.08 if i < n - 1 else 0), h, style="F")   # overlap: no seams in viewers
    pdf.set_draw_color(*RULE)
    pdf.set_line_width(0.2)
    pdf.rect(x, y, w, h)


def _heat(pdf: _ReportDoc, d: dict, L: dict, image: bytes | None):
    ht = d.get("heat")
    if not isinstance(ht, dict):
        return
    lines = _texts(ht.get("lines"))
    if not lines and not image:
        return
    st, W, x0 = pdf.st, pdf.epw, pdf.l_margin
    gap = st.item + 0.6
    if not image:
        _heading(pdf, L["heat"], need=_measure(pdf, lines[0], W, st.body)[0])
        for i, s in enumerate(lines):
            _advance(pdf, gap if i else 0.0, _measure(pdf, s, W, st.body)[0])
            _write(pdf, s, x0, W, st.body)
        return
    scale = _s(ht.get("scaleLabel"))
    if not scale and isinstance(ht.get("lo"), (int, float)) and isinstance(ht.get("hi"), (int, float)):
        scale = f"{_num(ht['lo'])} – {_num(ht['hi'])}"

    def block_for(iw: float) -> tuple[float, float]:
        """(height of the image, colour bar and scale beside the lines, scale label height) at image side iw."""
        hs = _measure(pdf, scale, iw, st.tiny)[0] if scale else 0.0
        text_h = sum(_measure(pdf, s, W - iw - 6.0, st.body)[0] for s in lines) + gap * max(0, len(lines) - 1)
        return max(iw + 6.0 + hs, text_h), hs

    iw = st.heat
    block, hs = block_for(iw)
    # an unsplittable block this tall would leave a large gap at the foot of the page: shrink the picture to the room
    # left (down to HEAT_MIN) before moving the section to the next page
    room = _room(pdf) - st.gap - _measure(pdf, L["heat"], W, st.head, True)[0] - 2.4
    if block > room and not _at_top(pdf):
        fit = room - 6.0 - hs
        if fit >= HEAT_MIN and block_for(fit)[0] <= room:
            iw = fit
            block, hs = block_for(iw)
    tx, tw = x0 + iw + 6.0, W - iw - 6.0
    _heading(pdf, L["heat"], need=block)
    y0 = pdf.get_y()
    pdf.image(io.BytesIO(image), x=x0, y=y0, w=iw, h=iw, keep_aspect_ratio=True)
    pdf.set_draw_color(*RULE)
    pdf.set_line_width(0.2)
    pdf.rect(x0, y0, iw, iw)
    _colour_bar(pdf, x0, y0 + iw + 2.0, iw, 3.0)
    if scale:
        pdf.set_y(y0 + iw + 6.0)                        # image, 2 mm, 3 mm colour bar, 1 mm
        _write(pdf, scale, x0, iw, st.tiny, color=MUTED, align="C")
    pdf.set_y(y0)
    for i, s in enumerate(lines):
        pdf.set_y(pdf.get_y() + (gap if i else 0.0))
        _write(pdf, s, tx, tw, st.body)
    pdf.set_y(y0 + block)


def _bullets(pdf: _ReportDoc, items: list[str], size: float, color=INK):
    st, x0 = pdf.st, pdf.l_margin
    ind = 4.6
    tw = pdf.epw - ind
    for i, text in enumerate(items):
        h, lh = _measure(pdf, text, tw, size)
        _advance(pdf, st.item * 0.8 if i else 0.0, h)
        y = pdf.get_y()
        pdf.set_fill_color(*MUTED)
        pdf.circle(x0 + 1.2, y + lh / 2, 0.6, style="F")
        _write(pdf, text, x0 + ind, tw, size, color=color)


def _reports(pdf: _ReportDoc, d: dict, L: dict):
    r = d.get("reports")
    if not isinstance(r, dict):
        return
    sentence, items = _s(r.get("sentence")), _texts(r.get("items"))
    if not sentence and not items:
        return
    st, W, x0 = pdf.st, pdf.epw, pdf.l_margin
    need = (_measure(pdf, sentence, W, st.body)[0] if sentence else 0.0) + \
        (_measure(pdf, items[0], W - 4.6, st.body)[0] + 1.2 if items else 0.0)
    _heading(pdf, L["reports"], need=need)
    if sentence:
        _write(pdf, sentence, x0, W, st.body)
        if items:
            pdf.set_y(pdf.get_y() + 1.2)
    _bullets(pdf, items, st.body)


def _actions(pdf: _ReportDoc, d: dict, L: dict):
    """This week's checklist: an empty box to tick per item, on a light panel (split across pages if it must)."""
    a = d.get("actions") if isinstance(d.get("actions"), dict) else {}
    title, items = _s(a.get("title")), _texts(a.get("items"))
    if not title and not items:
        return
    st, W, x0 = pdf.st, pdf.epw, pdf.l_margin
    pad, ind, box = 4.0, 7.2, 3.3
    inner = W - 2 * pad
    tw = inner - ind
    gap = st.item + 0.9
    if title == _s(L.get("actions")):      # the section heading already says it
        title = ""
    rows = [("title", title, _measure(pdf, title, inner, st.body, True))] if title else []
    rows += [("item", s, _measure(pdf, s, tw, st.body)) for s in items]
    gaps = [0.0] + [2.0 if rows[i - 1][0] == "title" else gap for i in range(1, len(rows))]
    first = sum(r[2][0] + g for r, g in zip(rows[:2], gaps[:2]))   # the title stays with the first item
    _heading(pdf, L["actions"], need=first + 2 * pad)
    i = 0
    while i < len(rows):
        room = _room(pdf) - 2 * pad
        j, used = i, 0.0
        while j < len(rows):
            add = (gaps[j] if j > i else 0.0) + rows[j][2][0]
            if used + add > room and j > i and not (rows[j - 1][0] == "title" and j - 1 == i):
                break
            used += add
            j += 1
        y0 = pdf.get_y()
        pdf.set_fill_color(*PANEL)
        pdf.rect(x0, y0, W, used + 2 * pad, style="F", round_corners=True, corner_radius=2.2)
        pdf.set_y(y0 + pad)
        for k in range(i, j):
            kind, text, (h, lh) = rows[k]
            if k > i:
                pdf.set_y(pdf.get_y() + gaps[k])
            y = pdf.get_y()
            if kind == "title":
                _write(pdf, text, x0 + pad, inner, st.body, bold=True)
                continue
            pdf.set_draw_color(*INK)
            pdf.set_line_width(0.3)
            pdf.set_fill_color(*WHITE)
            pdf.rect(x0 + pad, y + lh / 2 - box / 2, box, box, style="DF", round_corners=True, corner_radius=0.5)
            _write(pdf, text, x0 + pad + ind, tw, st.body)
        pdf.set_y(y0 + used + 2 * pad)
        i = j
        if i < len(rows):
            _new_page(pdf)


def _questions(pdf: _ReportDoc, d: dict, L: dict):
    qs = _texts(d.get("questions"))
    if not qs:
        return
    st, x0 = pdf.st, pdf.l_margin
    ind = 6.6
    tw = pdf.epw - ind
    _heading(pdf, L["questions"], need=_measure(pdf, qs[0], tw, st.body)[0])
    for i, q in enumerate(qs, 1):
        h, lh = _measure(pdf, q, tw, st.body)
        _advance(pdf, st.item if i > 1 else 0.0, h)
        y = pdf.get_y()
        _label(pdf, f"{i}.", x0, y, ind, lh, st.body, bold=True, color=ACCENT)
        pdf.set_y(y)
        _write(pdf, q, x0 + ind, tw, st.body)


def _limits(pdf: _ReportDoc, d: dict, L: dict):
    limits, sources = _texts(d.get("limits")), _s(d.get("sources"))
    if not limits and not sources:
        return
    st, W, x0 = pdf.st, pdf.epw, pdf.l_margin
    src_size = st.tiny + 0.2
    first = _measure(pdf, limits[0], W - 4.6, st.small)[0] if limits else _measure(pdf, sources, W, src_size)[0]
    _heading(pdf, L["limits"], need=first)
    _bullets(pdf, limits, st.small)
    if sources:
        _advance(pdf, 2.2 if limits else 0.0, _measure(pdf, sources, W, src_size)[0])
        _write(pdf, sources, x0, W, src_size, color=MUTED)


def _verification(pdf: _ReportDoc, d: dict, L: dict, qr: bytes | None):
    st, W, x0 = pdf.st, pdf.epw, pdf.l_margin
    q = 30.0
    tw = W - (q + 6.0 if qr else 0.0)
    lab, mono = st.tiny + 0.4, st.tiny + 0.3
    url = _s(d.get("verifyUrl"))
    rows = [(L[key], value, kind) for key, value, kind in (     # (label, value, kind)
        ("payload", _s(d.get("payloadSha256")), "mono"), ("key", _s(d.get("keyFingerprint")), "mono"),
        ("check", url, "url")) if value]
    how = L["checkHow"]

    def value_h(value: str, kind: str) -> float:
        if kind == "url":
            return _measure(pdf, value, tw, st.small)[0]
        key = ("mono", value, round(tw, 2), mono)
        if key not in pdf.mcache:
            _mono(pdf, mono)
            pdf.mcache[key] = pdf.multi_cell(tw, mono * PT * 1.35, value, dry_run=True,
                                             output=MethodReturnValue.HEIGHT)
        return pdf.mcache[key]

    text_h = sum((_measure(pdf, la, tw, lab)[0] if la else 0.0) + value_h(v, k) + 1.4 for la, v, k in rows)
    text_h += _measure(pdf, how, tw, st.small)[0] if how else 0.0
    block = max(q if qr else 0.0, text_h)
    _heading(pdf, L["verification"], need=block)
    y0 = pdf.get_y()
    if qr:
        pdf.image(io.BytesIO(qr), x=x0 + W - q, y=y0, w=q, h=q, link=url or None)
    for la, value, kind in rows:
        if la:
            _write(pdf, la, x0, tw, lab, color=MUTED)
        if kind == "url":
            _write(pdf, value, x0, tw, st.small, color=MEMORY, link=value)
        else:
            _mono(pdf, mono)
            pdf.set_text_color(*INK)
            pdf.set_x(x0)
            pdf.multi_cell(tw, mono * PT * 1.35, value, new_x=XPos.LEFT, new_y=YPos.NEXT)
        pdf.set_y(pdf.get_y() + 1.4)
    if how:
        _write(pdf, how, x0, tw, st.small, color=MUTED)
    pdf.set_y(max(pdf.get_y(), y0 + block))


# ------------------------------------------------------------------------------------------------ assembly

def _jpeg(data, max_px: int) -> bytes | None:
    if not data:
        return None
    try:
        return _img(bytes(data), max_px).getvalue()
    except Exception:            # an unreadable picture must not stop the report; the section is left out
        return None


def _png(data) -> bytes | None:
    if not data:
        return None
    try:
        from PIL import Image
        Image.open(io.BytesIO(bytes(data))).verify()
        return bytes(data)
    except Exception:
        return None


def _labels(d: dict) -> dict:
    L = dict(DEFAULT_LABELS)
    for k, v in (d.get("labels") if isinstance(d.get("labels"), dict) else {}).items():
        if isinstance(v, str) and v.strip():
            L[k] = v.strip()
    if not L["coords"] and isinstance(d.get("lat"), (int, float)) and isinstance(d.get("lon"), (int, float)):
        L["coords"] = f"{d['lat']:.5f} N, {d['lon']:.5f} E"
    return L


def _layout(d: dict, L: dict, st: _Style, assets: dict, break_before: str | None = None) -> _ReportDoc:
    lang = d.get("lang") if d.get("lang") in ("en", *SCRIPTS) else "en"
    needed = {lg for lg in (_lang_for(s, lang) for s in _strings(d)) if lg}
    pdf = _new_doc(needed | ({lang} if lang in SCRIPTS else set()))
    pdf.__class__ = _ReportDoc       # pdf.py's fonts and margins, the report's footer
    pdf.st, pdf.reader, pdf.mcache, pdf.gaps = st, lang, {}, []
    pdf.c_margin = 0                 # text starts on the margin, flush with rules, frames and markers
    pdf.page_label = L["page"]
    pdf.footer_text = L["footer"]
    pdf.report_id = _s(d.get("reportId")).upper()
    pdf.alias_nb_pages(TOTAL_ALIAS)
    pdf.set_lang(lang)
    pdf.set_title(" - ".join(s for s in (L["docTitle"], _s(d.get("title"))) if s))
    pdf.set_author("JalSmriti, made by Ansh Singhal")
    pdf.add_page()
    # footer: one line when a slightly smaller size allows it (no lone word on a second line), else wrapped, and its
    # height reserved above the bottom edge
    fw = pdf.epw - FOOT_RIGHT - 6
    sizes = (6.6,)
    if pdf.footer_text:
        one = [s for s in (6.6, 6.3, 6.0) if _width(pdf, pdf.footer_text, s) <= fw * 0.97]
        sizes = one[:1] or (6.6, 6.2, 5.8)
    for size in sizes:
        pdf.foot_size = size
        left = _measure(pdf, pdf.footer_text, fw, size)[0] if pdf.footer_text else 0.0
        pdf.foot_h = max(left, 2 * _lh(pdf, None, size))
        if pdf.foot_h <= 11.0:
            break
    pdf.set_auto_page_break(True, margin=max(20.0, pdf.foot_h + 14.0))     # 8 mm foot, rule, ~4 mm air above it

    _header(pdf, d, L)
    _title(pdf, d, L)
    sections = (
        ("memory", lambda: _memory(pdf, d, L)),
        ("verdict", lambda: _verdict(pdf, d, L)),
        ("findings", lambda: _findings(pdf, d, L)),
        ("timelapse", lambda: _timelapse(pdf, L, assets["frames"])),
        ("radar", lambda: _radar(pdf, d, L)),
        ("heat", lambda: _heat(pdf, d, L, assets["heat"])),
        ("reports", lambda: _reports(pdf, d, L)),
        ("actions", lambda: _actions(pdf, d, L)),
        ("questions", lambda: _questions(pdf, d, L)),
        ("limits", lambda: _limits(pdf, d, L)),
        ("verification", lambda: _verification(pdf, d, L, assets["qr"])),
    )
    for name, draw in sections:
        if name == break_before and not _at_top(pdf):
            _new_page(pdf)
        draw()
    return pdf


def _last_page_fill(pdf: _ReportDoc) -> float:
    if pdf.page_no() == 1:
        return 1.0
    return (pdf.get_y() - pdf.t_margin) / (pdf.page_break_trigger - pdf.t_margin)


def _quality(pdf: _ReportDoc) -> tuple[int, float, float]:
    """(pages, how full the last page is, the largest gap left at the foot of an earlier page in mm)."""
    return pdf.page_no(), _last_page_fill(pdf), max(pdf.gaps, default=0.0)


def render(d: dict) -> bytes:
    """The signed place report as PDF bytes.

    `d` carries every text already translated: lang, reportId, title, lat, lon, labels (docTitle, signedNote, checked,
    made, coords, memoryTitle, findings, timelapse, radar, heat, reports, actions, questions, limits, verification,
    payload, key, check, checkHow, footer, and page with {n} and {total}), tier, tierLabel, indexLabel, index,
    explain, validation, findings [{text, severity}], frames [{label, image}] (up to six, oldest first),
    radar {sentence, dates} | None, heat {lines, image, scaleLabel, lo, hi} | None, reports {sentence, items} | None,
    actions {title, items}, questions | None, limits, sources, payloadSha256, keyFingerprint, verifyUrl and qrPng,
    and for a family about to rent or buy, verdict {title, level, levelLabel, headline, whyTitle, why, prosTitle, pros,
    consTitle, cons, note} | None.
    A missing label falls back to English; empty sections and unreadable pictures are left out."""
    L = _labels(d)
    frames = d.get("frames") if isinstance(d.get("frames"), (list, tuple)) else []
    assets = {
        "frames": [(_s(f.get("label")), jpg) for f in frames[:6]
                   if isinstance(f, dict) and (jpg := _jpeg(f.get("image"), 420))],
        "heat": _jpeg((d.get("heat") or {}).get("image") if isinstance(d.get("heat"), dict) else None, 640),
        "qr": _png(d.get("qrPng")),
    }
    # the most comfortable density that fits two pages, ends on a page that is not nearly empty and leaves no large
    # gap; denser ones only when the comfortable ones run long
    tried = []
    for i, st in enumerate(_STYLES):
        pdf = _layout(d, L, st, assets)
        pages, fill, gap = _quality(pdf)
        if pages <= 2 and (pages == 1 or fill >= MIN_LAST_PAGE_FILL) and gap <= MAX_GAP:
            return bytes(pdf.output())
        tried.append((pages, fill, gap, i, pdf))
    full = [t for t in tried if t[0] == 1 or t[1] >= MIN_LAST_PAGE_FILL]
    if full:
        return bytes(min(full, key=lambda t: (t[0], t[2] > MAX_GAP, t[3]))[4].output())
    # every density ends on a nearly empty page (long content, or a short report whose verification block just
    # misses page one): carry whole closing sections over so the last page reads as a page
    pages, _, _, i, fallback = min(tried, key=lambda t: (t[0], t[3]))
    for name in ("limits", "questions", "actions", "reports", "heat", "radar"):
        pdf = _layout(d, L, _STYLES[i], assets, break_before=name)
        if pdf.page_no() == pages and _last_page_fill(pdf) >= MIN_LAST_PAGE_FILL:
            return bytes(pdf.output())
    return bytes(fallback.output())
