"""Listen: a place or lake report read aloud by Amazon Polly with the neural voice Kajal, one voice that speaks both
Indian English (en-IN) and Hindi (hi-IN).

Audio is cached by everything that makes it unique (voice, engine, language and text): pub/speech/<key>.mp3 is
written once with an immutable cache header and served by CloudFront, so a report is synthesized only once however
often it is played. In the local stack and tests Polly is not called: about a second of two soft notes (a WAV)
stands in, so the page's player can be tried without AWS.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache

from . import config as C
from . import storage

VOICE = "Kajal"
ENGINE = "neural"
# where Kajal's neural voice is not offered, the standard voice Aditi (also Hindi and Indian English) reads instead
FALLBACK_VOICE, FALLBACK_ENGINE = "Aditi", "standard"
LANGUAGE_CODES = {"hi": "hi-IN", "en": "en-IN"}
MAX_CHARS = 2900      # SynthesizeSpeech takes at most 3,000 billed characters of plain text per request
# a sentence ends at . ! ? or the Devanagari danda (U+0964, U+0965), with any closing quote or bracket
_SENTENCE_END = re.compile("[.!?\u0964\u0965][\"')\\]]*(?=\\s|$)")


def trim(text: str, limit: int = MAX_CHARS) -> str:
    """Whitespace collapsed, then cut after the last sentence that ends within `limit` characters (or at the last
    space when no sentence ends that early)."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    ends = [m.end() for m in _SENTENCE_END.finditer(text) if m.end() <= limit]
    if ends:
        return text[:ends[-1]]
    cut = text.rfind(" ", 0, limit + 1)
    return text[:cut if cut > 0 else limit].rstrip()


def cache_key(text: str, lang: str) -> str:
    return hashlib.sha256(f"{VOICE}|{ENGINE}|{lang}|{text}".encode("utf-8")).hexdigest()[:24]


@lru_cache(maxsize=1)
def _polly():
    import boto3
    from botocore.config import Config
    return boto3.client("polly", region_name=C.REGION, config=Config(retries={"max_attempts": 4, "mode": "standard"}))


def chime(seconds: float = 1.0, rate: int = 16000) -> bytes:
    """About a second of two soft sine notes (C5, then E5), 16-bit mono at 16 kHz: the local stand-in for speech."""
    import array
    import io
    import math
    import sys
    import wave
    n = int(seconds * rate)
    samples = [0.0] * n
    for freq, start, length in ((523.25, 0.04, 0.42), (659.25, 0.5, 0.46)):
        s0, m = int(start * rate), int(length * rate)
        attack, release = 0.02 * rate, 0.18 * rate          # gentle fade in and out, no clicks
        for i in range(min(m, n - s0)):
            env = min(1.0, i / attack, (m - i) / release)
            samples[s0 + i] += 0.2 * env * math.sin(2 * math.pi * freq * i / rate)
    pcm = array.array("h", (int(round(max(-1.0, min(1.0, v)) * 32767)) for v in samples))
    if sys.byteorder == "big":                              # WAV is little-endian
        pcm.byteswap()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def synthesize(text: str, lang: str) -> dict:
    """Speech for `text` in Hindi ("hi") or English ("en"), published under /pub/speech/ (cached by content).

    Returns {"url", "voice", "engine", "chars", "cached", "local"}; `url` is site-relative (/pub/speech/<key>.mp3,
    or .wav from the local stand-in). Raises ValueError for any other language or an empty text.
    """
    if lang not in LANGUAGE_CODES:
        raise ValueError("narration is available in Hindi (hi) and English (en) only")
    text = trim(text)
    if not text:
        raise ValueError("there is nothing to read aloud")
    key = cache_key(text, lang)
    local = bool(C.LOCAL)
    path = f"speech/{key}.{'wav' if local else 'mp3'}"
    cached = storage.exists(C.SITE_BUCKET or "site", storage.public_key(path))
    voice, engine = VOICE, ENGINE
    if not cached:
        if local:
            audio, content_type = chime(), "audio/wav"
        else:
            audio, voice, engine = _speak(text, LANGUAGE_CODES[lang])
            content_type = "audio/mpeg"
        storage.put_public(path, audio, content_type, immutable=True)
    return {"url": "/" + storage.public_key(path), "voice": voice, "engine": engine, "chars": len(text),
            "cached": cached, "local": local}


def _speak(text: str, language_code: str) -> tuple[bytes, str, str]:
    """MP3 from Kajal (neural); from Aditi (standard) where this Region does not offer Kajal's neural voice."""
    from botocore.exceptions import ClientError
    try:
        r = _polly().synthesize_speech(Text=text, TextType="text", VoiceId=VOICE, Engine=ENGINE,
                                       LanguageCode=language_code, OutputFormat="mp3")
        return r["AudioStream"].read(), VOICE, ENGINE
    except ClientError as ex:
        if ex.response.get("Error", {}).get("Code") not in ("EngineNotSupportedException", "ValidationException",
                                                             "InvalidParameterValueException", "LanguageNotSupportedException"):
            raise
    r = _polly().synthesize_speech(Text=text, TextType="text", VoiceId=FALLBACK_VOICE, Engine=FALLBACK_ENGINE,
                                   LanguageCode=language_code, OutputFormat="mp3")
    return r["AudioStream"].read(), FALLBACK_VOICE, FALLBACK_ENGINE
