"""Translating letters into Indian languages and Nepali without ever changing a number.

Amazon Translate handles Hindi, Kannada, Tamil, Telugu, Malayalam, Marathi, Bengali, Gujarati, Punjabi and Urdu.
Numbers, dates and IDs are wrapped in do-not-translate spans first. Nepali, Assamese and Odia are not in Amazon
Translate, so Amazon Nova (Bedrock) translates them with the same protected spans and the result is labelled
machine-translated. Either way code then checks that every number in the translation was in the English.
"""
from __future__ import annotations

import html
import json
import logging
import re
from functools import lru_cache

from . import config as C

log = logging.getLogger(__name__)

# native digits of the scripts we write -> ASCII
_DIGITS = {
    "०१२३४५६७८९": "hi/mr/ne", "০১২৩৪৫৬৭৮৯": "bn/as", "੦੧੨੩੪੫੬੭੮੯": "pa", "૦૧૨૩૪૫૬૭૮૯": "gu", "୦୧୨୩୪୫୬୭୮୯": "or",
    "௦௧௨௩௪௫௬௭௮௯": "ta", "౦౧౨౩౪౫౬౭౮౯": "te", "೦೧೨೩೪೫೬೭೮೯": "kn", "൦൧൨൩൪൫൬൭൮൯": "ml", "۰۱۲۳۴۵۶۷۸۹": "ur", "٠١٢٣٤٥٦٧٨٩": "ar"}
DIGIT_MAP = str.maketrans({d: str(i) for digits in _DIGITS for i, d in enumerate(digits)})

LANG_NAMES = {"en": "English", "hi": "Hindi", "kn": "Kannada", "ta": "Tamil", "te": "Telugu", "ml": "Malayalam",
              "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati", "pa": "Punjabi", "ur": "Urdu", "ne": "Nepali",
              "as": "Assamese", "or": "Odia"}

_PROTECT = re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b|[A-Za-z]+-[a-z0-9]{6,}\d*|\d[\d,]*(?:\.\d+)?%?")
_SPAN = re.compile(r'<span\s+translate\s*=\s*"?no"?\s*>(.*?)</span>', re.S | re.I)


def normalise_digits(text: str) -> str:
    return text.translate(DIGIT_MAP)


def numbers_in(text: str) -> list[str]:
    t = normalise_digits(text).replace(",", "")
    return re.findall(r"(?<![\w.])\d+(?:\.\d+)?", t)


def protect(text: str) -> str:
    out, pos = [], 0
    for m in _PROTECT.finditer(text):
        out.append(html.escape(text[pos:m.start()], quote=False))
        out.append(f'<span translate="no">{m.group(0)}</span>')
        pos = m.end()
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def unprotect(text: str) -> str:
    text = _SPAN.sub(lambda m: m.group(1), text)
    text = re.sub(r"</?span[^>]*>", "", text)
    return html.unescape(text).strip()


@lru_cache(maxsize=1)
def _translate_client():
    import boto3
    return boto3.client("translate", region_name=C.REGION)


def _amazon_translate(text: str, target: str) -> str:
    out = []
    for para in text.split("\n"):
        if not para.strip():
            out.append(para)
            continue
        r = _translate_client().translate_text(Text=protect(para), SourceLanguageCode="en", TargetLanguageCode=target)
        out.append(unprotect(r["TranslatedText"]))
    return "\n".join(out)


def _bedrock_translate(text: str, target: str) -> str:
    from .bedrock import converse_text
    lang = LANG_NAMES[target]
    prompt = (f"Translate the text below from English into {lang}. Keep the same paragraphs and line breaks. "
              f"Text inside <span translate=\"no\">...</span> must be copied exactly, unchanged, including the tags. "
              f"Write numbers with the same digits as given. Reply with the translation only.\n\n{protect(text)}")
    return unprotect(converse_text(prompt, system=f"You are a careful professional translator into {lang}.",
                                   max_tokens=2500, temperature=0.1))


def translate(text: str, target: str) -> dict:
    """{'text', 'engine', 'machine', 'numbersOk'}; raises ValueError if numbers changed after one retry."""
    if target == "en" or not text.strip():
        return {"text": text, "engine": "original", "machine": False, "numbersOk": True}
    if C.LOCAL:
        return {"text": f"[{LANG_NAMES.get(target, target)} translation is produced by Amazon Translate when deployed]\n{text}",
                "engine": "local stand-in", "machine": True, "numbersOk": True}
    engines = ([("Amazon Translate", _amazon_translate)] if target in C.TRANSLATE_SUPPORTED else []) + \
              [("Amazon Nova (Amazon Bedrock)", _bedrock_translate)]
    want = sorted(numbers_in(text))
    last = None
    for name, fn in engines:
        for _attempt in range(2):
            try:
                out = fn(text, target)
            except Exception as ex:
                last = ex
                log.warning("%s failed for %s: %s", name, target, ex)
                break
            got = sorted(numbers_in(out))
            if set(got) == set(want):
                return {"text": out, "engine": name, "machine": True, "numbersOk": True}
            last = ValueError(f"{name} changed numbers: {sorted(set(got) - set(want))}")
    raise ValueError(f"could not translate into {LANG_NAMES.get(target, target)} with numbers intact ({last})")
