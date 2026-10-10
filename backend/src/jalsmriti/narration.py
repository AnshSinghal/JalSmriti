"""The words JalSmriti reads aloud (speech.synthesize) for a place check or a lake, in the listener's language.

Short spoken sentences built from the same keys the page uses (place.memory.*, grade.*, f.*) plus "speech.*" keys
for what only the narration says. SPEECH_EN holds the English defaults, used until the dictionaries carry the keys.
Units are written out the way a listener hears them ("12 hectares", "40 percent", "1984 to 2020").
"""
from __future__ import annotations

import re

from . import config as C
from . import strings

SPEECH_EN = {
    "speech.placeIntro": "Water memory report for {place}.",
    "speech.coords": "the place at {lat} north, {lon} east",
    "speech.memory": "{tier}: {index}.",
    "speech.memoryNone": "There is not enough satellite data to give this place a water memory score.",
    "speech.radarNone": "In {scenes} monsoon radar passes since {year}, no unusual standing water was seen within "
                        "300 metres. Radar cannot see between tall buildings, so this does not mean it never floods.",
    "speech.radarOne": "Since {year}, monsoon radar saw unusual standing water within 300 metres once in {scenes} "
                       "passes, on {date}.",
    "speech.radarSome": "Since {year}, monsoon radar saw unusual standing water within 300 metres {n} times in "
                        "{scenes} passes, most recently on {date}.",
    "speech.radarNoData": "Monsoon radar passes could not be checked for this place.",
    "speech.heat": "On summer mornings, satellites measure the ground here at about {here}°C, {built}, and {water}.",
    "speech.heatOne": "On summer mornings, satellites measure the ground here at about {here}°C, {other}.",
    "speech.heatOnly": "On summer mornings, satellites measure the ground here at about {here}°C.",
    "speech.heat.builtCooler": "{d}°C cooler than nearby built-up ground",
    "speech.heat.builtWarmer": "{d}°C warmer than nearby built-up ground",
    "speech.heat.builtSame": "about as warm as nearby built-up ground",
    "speech.heat.waterCooler": "{d}°C cooler than nearby water",
    "speech.heat.waterWarmer": "{d}°C warmer than nearby water",
    "speech.heat.waterSame": "about as warm as nearby water",
    "speech.actions": "What to do this week:",
    "speech.placeEnd": "This describes the history and terrain of this place. It is not a flood forecast.",
    "speech.lakeIntro": "Health report for {name}.",
    "speech.unnamedLake": "this water body",
    "speech.grade": "Health grade {grade}: {label}.",
    "speech.gradeScore": "Health grade {grade}: {label}, {score} of 100.",
    "speech.gradeNone": "This water body has no health grade.",
    "speech.lakeEnd": "If you know this lake, add your photos on JalSmriti and prepare a signed complaint to the "
                      "authorities who can protect it.",
    "speech.hectares": "hectares",
    "speech.percent": "percent",
    "speech.celsius": "degrees Celsius",
    "speech.yearRange": "{from} to {to}",
}

# English defaults of the page's own keys, used only until data/ui_strings.json is exported
TIER_EN = {"strong": "Strong water memory", "some": "Some water memory", "little": "Little water memory",
           "unknown": "Not enough data"}
GRADE_EN = {"A": "Healthy", "B": "Under pressure", "C": "Damaged", "D": "Badly damaged", "E": "Being lost"}

_YEARS = re.compile(r"\b((?:19|20)\d\d)\s?[-\u2013\u2014]\s?((?:19|20)\d\d)\b")   # 1984-2020, 1984 - 2020, 1984–2020
_HECTARES = re.compile(r"(?<=\d)\s?ha\b")                                        # 12.5 ha, 3ha
_PERCENT = re.compile(r"\s?%")                                                   # 40%, 40 %
_CELSIUS = re.compile("\\s?(?:\u00b0\\s?C\\b|\u2103)")                                 # 41°C, 41 °C, 41℃
_ISO_DATE = re.compile(r"\b(?:19|20)\d\d-[01]\d-[0-3]\d\b")
_END = ".!?\u0964\u0965"


def _t(lang: str, key: str, **vars) -> str:
    return strings.t(lang, key, en=SPEECH_EN[key], **vars)


def _sentence(s: str | None, lang: str = "en") -> str:
    """A full stop if the sentence has none (the danda in Hindi and Nepali)."""
    s = (s or "").strip()
    return s if not s or s[-1] in _END else s + ("\u0964" if lang in ("hi", "ne") else ".")


def _tier_label(tier: str, lang: str) -> str:
    s = strings.tier_label(tier, lang)
    return TIER_EN.get(tier, s) if s == f"place.memory.{tier}" else s


def _finding(f: dict, lang: str) -> str:
    """strings.finding_text, or the stored English while the dictionaries have no f.* keys yet (its ISO dates are
    then written as the page writes them, "4 Oct 2026", which a voice reads as a date)."""
    key = f"f.{f.get('key')}"
    s = strings.finding_text(f, lang) if f.get("vars") is not None and strings.has(strings.lang_or_en(lang), key) else ""
    if not s.strip() or s.startswith(key):
        s = _ISO_DATE.sub(lambda m: strings.day(m.group(0), lang), f.get("text") or "")
    return _sentence(s, lang)


def _findings(findings: list[dict], lang: str, limit: int = 4) -> list[str]:
    return [s for s in (_finding(f, lang) for f in findings) if s][:limit]


# full month names for the voice: written dates use short months ("4 Oct 2026", "4 अक्टू॰ 2026"), which a voice
# would spell out; Polly speaks only Hindi and English here
_MONTHS_FULL = {
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"),
    "hi": ("जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"),
}


def _full_months(text: str, lang: str) -> str:
    names = _MONTHS_FULL.get(lang)
    if not names:
        return text
    for n in range(12, 0, -1):
        short = strings.t(lang, f"month.{n}", ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
                                               "Nov", "Dec")[n - 1])
        text = re.sub(rf"(\d{{1,2}}) {re.escape(short)} (\d{{4}})", rf"\1 {names[n - 1]} \2", text)
    return text


def speakable(text: str, lang: str) -> str:
    """Units written out for text-to-speech: "12 ha" -> "12 hectares", "40%" -> "40 percent", "41°C" -> "41 degrees
    Celsius", "1984-2020" -> "1984 to 2020", "4 Oct 2026" -> "4 October 2026", in `lang`. Everything else is left
    as it is."""
    text = _full_months(text, lang)
    words = {k: _t(lang, k) for k in ("speech.hectares", "speech.percent", "speech.celsius")}
    text = _YEARS.sub(lambda m: _t(lang, "speech.yearRange", **{"from": m.group(1), "to": m.group(2)}), text)
    text = _HECTARES.sub(lambda m: " " + words["speech.hectares"], text)
    text = _PERCENT.sub(lambda m: " " + words["speech.percent"], text)
    return _CELSIUS.sub(lambda m: " " + words["speech.celsius"], text)


# ---------------------------------------------------------------------------------------------- places
def _radar(result: dict, lang: str) -> str:
    sightings = [s for s in ((result.get("signals") or {}).get("radarSightings") or []) if isinstance(s, dict)]
    scenes = int((result.get("radar") or {}).get("scenesChecked") or 0)
    year = C.S1_FIRST_YEAR
    if not sightings:
        return _t(lang, "speech.radarNone", scenes=strings.num(scenes), year=year) if scenes else _t(lang, "speech.radarNoData")
    scenes = max(scenes, len(sightings))
    date = strings.day(max(str(s.get("date") or "") for s in sightings), lang)
    if len(sightings) == 1:
        return _t(lang, "speech.radarOne", scenes=strings.num(scenes), year=year, date=date)
    return _t(lang, "speech.radarSome", n=len(sightings), scenes=strings.num(scenes), year=year, date=date)


def _heat(heat, lang: str) -> str:
    """One sentence: summer ground temperature here, against nearby built-up ground and nearby water."""
    if not isinstance(heat, dict) or heat.get("hereC") is None:
        return ""
    here = float(heat["hereC"])
    phrases = {}
    for name in ("built", "water"):
        other, vs = heat.get(f"{name}C"), heat.get(f"vs{name.capitalize()}C")
        if other is not None:
            d = here - float(other)                  # from the temperatures themselves: no sign convention to trust
        elif vs is not None:
            d = float(vs)                            # here minus there
        else:
            continue
        r = round(abs(d))
        word = "Same" if r == 0 else "Warmer" if d > 0 else "Cooler"
        phrases[name] = _t(lang, f"speech.heat.{name}{word}", d=strings.num(r, 0))
    t = strings.num(here, 0)
    if len(phrases) == 2:
        return _t(lang, "speech.heat", here=t, built=phrases["built"], water=phrases["water"])
    if phrases:
        return _t(lang, "speech.heatOne", here=t, other=next(iter(phrases.values())))
    return _t(lang, "speech.heatOnly", here=t)


def place_text(result: dict, lang: str, actions: list[str] | None = None) -> str:
    """What a place check says, as short spoken sentences: the place, its water memory, up to four findings, radar,
    summer heat (when known), up to three actions for this week (already in `lang`) and what this is not."""
    lang = strings.lang_or_en(lang)
    label = result.get("label")
    name = (label.get("label") if isinstance(label, dict) else label) or ""
    if not name.strip() and result.get("lat") is not None and result.get("lon") is not None:
        name = _t(lang, "speech.coords", lat=f"{float(result['lat']):.3f}", lon=f"{float(result['lon']):.3f}")
    parts = [_t(lang, "speech.placeIntro", place=name.strip()) if name.strip() else ""]
    memory = result.get("memory") or {}
    tier = memory.get("tier") or "unknown"
    if memory.get("index") is not None and tier != "unknown":
        index = strings.t(lang, "place.memory.index", en="{n} of 100", n=strings.num(memory["index"], 0))
        parts.append(_t(lang, "speech.memory", tier=_tier_label(tier, lang), index=index))
    else:
        parts.append(_t(lang, "speech.memoryNone"))
    # radar sightings are told once, in the radar sentence, instead of one finding per pass
    findings = [f for f in (result.get("findings") or []) if isinstance(f, dict) and f.get("key") != "radar"]
    parts += _findings(findings, lang)
    parts.append(_radar(result, lang))
    parts.append(_heat(result.get("heat"), lang))
    acts = [a.strip() for a in (actions or []) if isinstance(a, str) and a.strip()][:3]
    if acts:
        parts.append(_t(lang, "speech.actions"))
        parts += [_sentence(a, lang) for a in acts]
    parts.append(_t(lang, "speech.placeEnd"))
    return speakable(" ".join(p for p in parts if p), lang)


# ---------------------------------------------------------------------------------------------- lakes
def lake_text(lake: dict, lang: str) -> str:
    """What a lake page says, spoken: its name, health grade, up to four findings and how to help."""
    lang = strings.lang_or_en(lang)
    name = str(lake.get("name") or "").strip() or _t(lang, "speech.unnamedLake")
    parts = [_t(lang, "speech.lakeIntro", name=name)]
    grade = (lake.get("metrics") or {}).get("grade") or {}
    letter = grade.get("grade")
    if letter:
        label = strings.t(lang, f"grade.{letter}", en=GRADE_EN.get(letter, str(letter)))
        if grade.get("score") is not None:
            parts.append(_t(lang, "speech.gradeScore", grade=letter, label=label, score=strings.num(grade["score"], 0)))
        else:
            parts.append(_t(lang, "speech.grade", grade=letter, label=label))
    else:
        parts.append(_t(lang, "speech.gradeNone"))
    parts += _findings([f for f in (lake.get("findings") or []) if isinstance(f, dict)], lang)
    parts.append(_t(lang, "speech.lakeEnd"))
    return speakable(" ".join(p for p in parts if p), lang)
