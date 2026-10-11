"""Dossiers: letters only use computed numbers, translations keep them, PDFs render, signatures verify."""
import base64
import hashlib

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from jalsmriti import areas as A
from jalsmriti import dossier as D
from jalsmriti import pdf, signing
from jalsmriti import translate as T

FACTS = {"lakeName": "Test Kere", "lakeId": "ben-abc1234", "lat": 12.935, "lon": 77.665, "historicHa": 40.0, "lostHa": 12.5,
         "lostPct": 31.2, "builtHa": 2.5, "builtPct": 6.2, "retentionPct": 55, "weedPct": 41.0, "qualityDate": "2026-10-04",
         "storageLowML": 125, "storageHighML": 250, "grade": "C", "score": 55, "evidenceCount": 2, "verifiedCount": 1,
         "recipient": "Greater Bengaluru Authority", "laws": ["Wetlands (Conservation and Management) Rules, 2017"],
         "series": [{"season": 1990, "waterHa": 38.0, "source": "LS"}, {"season": 2025, "waterHa": 22.0, "source": "S2"}]}


def test_template_letter_uses_only_computed_numbers():
    letter = D.template_letter(FACTS)
    assert D.unsupported_numbers(letter["subject"] + "\n" + letter["body"], FACTS) == []
    assert "2 photographs" in letter["body"] and "1 of them" in letter["body"]
    assert "4 October 2026" in letter["body"]
    assert len(letter["asks"]) == 5


def test_number_check_catches_invented_figures():
    bad = "About 75 ha of the lake has been lost since 1984, and 12.5 ha is built over."
    assert D.unsupported_numbers(bad, FACTS) == ["75"]


def test_local_draft_falls_back_to_the_template():
    letter = D.draft_letter(FACTS, [], {"name": "Greater Bengaluru Authority"})
    assert letter["model"].startswith("template")
    assert letter["subject"].startswith("Request for inspection")


def test_translation_must_keep_every_number(monkeypatch):
    monkeypatch.setattr(T.C, "LOCAL", False)
    monkeypatch.setattr(T, "_amazon_translate", lambda text, target: text.replace("12.5", "13"))
    monkeypatch.setattr(T, "_bedrock_translate", lambda text, target: "ಕೆರೆ " + text)
    r = T.translate("12.5 ha of water was lost; 55% held.", "kn")
    assert r["engine"].startswith("Amazon Nova") and r["numbersOk"]

    monkeypatch.setattr(T, "_bedrock_translate", lambda text, target: text.replace("55", "56"))
    with pytest.raises(ValueError):
        T.translate("12.5 ha of water was lost; 55% held.", "kn")


def test_native_digits_count_as_the_same_numbers():
    assert T.numbers_in("೧೨.೫ ಹೆಕ್ಟೇರ್, ५५%") == ["12.5", "55"]
    assert T.unprotect(T.protect("Lake ben-tdr1x6u lost 12.5 ha")) == "Lake ben-tdr1x6u lost 12.5 ha"


def test_signature_verifies_in_webcrypto_form():
    digest = hashlib.sha256(b'{"dossierId":"ds-1"}').digest()
    sig = signing.sign_digest(digest)
    assert signing.verify(digest, sig["der"])
    raw = base64.b64decode(sig["raw"])
    assert len(raw) == 64                                    # r||s, what the browser's Web Crypto API expects
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key = serialization.load_der_public_key(base64.b64decode(signing.public_key()["spki"]))
    key.verify(der, b'{"dossierId":"ds-1"}', ec.ECDSA(hashes.SHA256()))   # raises if invalid
    assert not signing.verify(hashlib.sha256(b"something else").digest(), sig["der"])


@pytest.mark.parametrize("lang", ["hi", "kn", "ta", "ur"])
def test_pdf_renders_in_each_script(lang):
    letter = D.template_letter(FACTS)
    record = {"dossierId": "ds-test", "lakeId": "ben-abc1234", "createdAt": "2026-10-10T10:00:00Z", "facts": FACTS,
              "letter": letter, "recipient": {"name": "Greater Bengaluru Authority"}, "language": lang,
              "translation": {"subject": "विषय 12.5", "body": "पाठ 40 हेक्टेयर", "asks": ["एक", "दो"], "engine": "test"},
              "payloadSha256": "a" * 64, "ledger": {"seq": 3, "hash": "b" * 64}, "keyFingerprint": "c" * 32}
    out = pdf.render(record, [], [], None, "https://example.test/verify/ds-test")
    assert out.startswith(b"%PDF-") and len(out) > 20_000


def test_every_area_has_authorities_and_laws():
    for a in A.AREAS.values():
        assert a.authorities and a.laws and a.events, a.id
        assert all(e["date"] and e["title"] and e["detail"] for e in a.events)
        assert a.bbox[0] < a.bbox[2] and a.bbox[1] < a.bbox[3]


def test_a_refused_amazon_translate_hands_every_letter_to_nova(monkeypatch):
    """AWS's new Free Tier has no Amazon Translate: the first refusal switches all later letters straight to Nova."""
    from botocore.exceptions import ClientError
    calls = []

    class Refusing:
        def translate_text(self, **kw):
            calls.append(kw)
            raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "with an explicit deny in a service "
                                         "control policy"}}, "TranslateText")

    monkeypatch.setattr(T.C, "LOCAL", False)
    monkeypatch.setattr(T, "_translate_client", lambda: Refusing())
    monkeypatch.setitem(T._TRANSLATE_REFUSED, "refused", False)
    monkeypatch.setattr(T, "_bedrock_translate", lambda text, target: "ಕೆರೆ " + text)
    for _ in range(3):
        r = T.translate("12.5 ha of water was lost; 55% held.", "kn")
        assert r["engine"].startswith("Amazon Nova") and r["numbersOk"]
    assert len(calls) == 1
