"""Async jobs worker (SQS): builds, renders and signs evidence dossiers and place reports."""
from __future__ import annotations

import hashlib
import io
import json
import logging

from jalsmriti import areas as A
from jalsmriti import dossier as D
from jalsmriti import ledger, pdf, placereport, report_pdf, signing, storage, store, waterlog
from jalsmriti import config as C

log = logging.getLogger()
log.setLevel(logging.INFO)


def _public_bytes(url_path: str) -> bytes | None:
    """Read an object we published under /pub/ (straight from the bucket, not over HTTP)."""
    try:
        return storage.get(C.SITE_BUCKET or "site", url_path.lstrip("/"))
    except Exception:
        return None


def _qr(url: str) -> bytes | None:
    try:
        import segno
        buf = io.BytesIO()
        segno.make(url, error="m").save(buf, kind="png", scale=6, border=2)
        return buf.getvalue()
    except Exception:
        return None


def build_dossier(dossier_id: str) -> dict:
    d = store.get(f"DOSS#{dossier_id}")
    if not d:
        raise ValueError(f"unknown dossier {dossier_id}")
    if d.get("status") not in ("drafting", "failed"):
        return d
    lake = store.get(f"LAKE#{d['lakeId']}")
    area = A.AREAS.get(lake.get("areaId") or "")
    evid = store.query_all(f"LAKE#{d['lakeId']}", "EVID#", index="GSI1")
    evid = [e for e in evid if e.get("status") in ("new", "verified")]
    evid.sort(key=lambda e: (e.get("status") != "verified", e.get("createdAt", "")), reverse=False)
    chosen = [e for e in evid if e["evidenceId"] in set(d.get("evidenceIds") or [])] or evid[:6]
    laws = (area.laws if area else (A.LAW_NP if (lake.get("admin") or {}).get("countryCode") == "np" else A.LAW_IN))
    recipient = d.get("recipient") or {"name": "The competent authority"}
    facts = D.build_facts(lake, area, chosen, recipient, list(laws))
    letter = D.draft_letter(facts, chosen, recipient)
    lang = d.get("language", "hi")
    try:
        translation = D.translate_letter(letter, lang)
    except Exception as ex:
        log.warning("translation failed: %s", ex)
        translation = {"error": str(ex)[:200], "language": lang}
    head = store.get(f"LEDGER#{d['lakeId']}", "HEAD") or {"seq": 0, "hash": ledger.GENESIS}
    frames = [f for f in (lake.get("frames") or [])]
    picks = []
    if frames:
        seasons = [f for f in frames if f != "latest"]
        idx = sorted({0, len(seasons) // 3, (2 * len(seasons)) // 3, len(seasons) - 1}) if seasons else []
        picks = [seasons[i] for i in idx if 0 <= i < len(seasons)] + (["latest"] if "latest" in frames else [])
    crops = []
    for s in picks[:6]:
        b = _public_bytes(f"pub/lakes/{d['lakeId']}/frames/{s}.webp")
        if b:
            crops.append((str(s) if s != "latest" else (lake.get("latestDate") or "latest"), b))
    ev_imgs = []
    for e in chosen[:6]:
        b = _public_bytes(e["thumbUrl"]) if e.get("thumbUrl") else None
        if b:
            ev_imgs.append((e, b))
    payload = {"dossierId": dossier_id, "lakeId": d["lakeId"], "createdAt": d["createdAt"], "creator": d.get("creator"),
               "recipient": recipient, "language": lang, "facts": facts, "letter": {k: letter[k] for k in ("subject", "body", "asks")},
               "translation": {k: translation.get(k) for k in ("subject", "body", "asks", "engine")} if translation and not translation.get("error") else None,
               "evidence": [{"id": e["evidenceId"], "sha256": e.get("sha256"), "capturedAt": e.get("capturedAt"),
                             "gps": e.get("gps"), "gpsCheck": e.get("gpsCheck"), "status": e.get("status")} for e in chosen],
               "frames": picks, "ledger": {"seq": head.get("seq", 0), "hash": head.get("hash")},
               "scienceVersion": C.SCIENCE_VERSION, "model": letter.get("model")}
    payload_sha = ledger.sha256_hex(ledger.canonical(payload))
    site = storage.site_url()
    verify_url = f"{site}/verify/{dossier_id}" if site else f"/verify/{dossier_id}"
    key = signing.public_key()
    record = {**d, "facts": facts, "letter": letter, "translation": translation, "payloadSha256": payload_sha,
              "ledger": payload["ledger"], "keyFingerprint": key["fingerprint"], "language": lang}
    pdf_bytes = pdf.render(record, crops, ev_imgs, _qr(verify_url), verify_url)
    pdf_sha = ledger.sha256_hex(pdf_bytes)
    pdf_url = storage.put_public(f"dossiers/{dossier_id}.pdf", pdf_bytes, "application/pdf", immutable=True)
    attestation = {"dossierId": dossier_id, "payloadSha256": payload_sha, "pdfSha256": pdf_sha, "signedAt": store.now_iso(),
                   "keyFingerprint": key["fingerprint"], "issuer": "JalSmriti"}
    canon = ledger.canonical(attestation)
    sig = signing.sign_digest(hashlib.sha256(canon).digest())
    entry = ledger.append(d["lakeId"], "dossier", dossier_id, payload_sha, d.get("creator", "citizen"))
    sets = {"status": "ready", "facts": facts, "letter": letter, "translation": translation, "payload": payload,
            "payloadSha256": payload_sha, "pdfSha256": pdf_sha, "pdfUrl": pdf_url, "attestation": attestation,
            "attestationCanonical": canon.decode("utf-8"), "signature": sig, "keyFingerprint": key["fingerprint"],
            "ledgerSeq": entry["seq"], "readyAt": store.now_iso(), "GSI3SK": f"ready#{d['createdAt']}",
            "timeline": (d.get("timeline") or []) + [{"at": store.now_iso(), "status": "ready", "by": "JalSmriti",
                                                       "note": f"Letter by {letter.get('model')}; signed; PDF {round(len(pdf_bytes) / 1024)} KB"}]}
    store.update(f"DOSS#{dossier_id}", "META", sets=sets)
    store.bump_stats(dossiers=1)
    return {**d, **sets}


def build_report(report_id: str) -> dict:
    """Render the place report PDF in the reader's language and sign what it says with the KMS key."""
    r = store.get(f"RPT#{report_id}")
    if not r:
        raise ValueError(f"unknown report {report_id}")
    if r.get("status") == "ready":
        return r
    place = store.get(f"PLACE#{r['gh7']}", f"V#{C.PLACE_CACHE_VERSION}")
    if not place:
        raise ValueError("the place check has expired: check the place again")
    frames = []
    seasons = [f for f in (place.get("frames") or []) if f.get("url")]
    if seasons:
        idx = sorted({round(i * (len(seasons) - 1) / 5) for i in range(6)}) if len(seasons) > 6 else range(len(seasons))
        for i in idx:
            b = _public_bytes(seasons[i]["url"])
            if b:
                frames.append((str(seasons[i]["season"]), b))
    heat = place.get("heat") or {}
    heat_img = _public_bytes(heat["imageUrl"]) if heat.get("imageUrl") else None
    try:
        nearby = waterlog.nearby(float(r["lat"]), float(r["lon"]), 1000, 365)
    except Exception as ex:
        log.warning("nearby reports failed: %s", ex)
        nearby = None
    payload = placereport.payload(r, place)
    payload["waterReports"] = (nearby or {}).get("count")
    if payload.get("answers"):                    # the verdict the report gives, so the signature covers it too
        from jalsmriti import verdict as V
        v = V.build(place, payload["answers"], (nearby or {}).get("count") or 0)
        payload["verdict"] = {"level": v["level"], "points": v["points"],
                              "keys": [x["key"] for x in v["why"] + v["pros"] + v["cons"]]}
    payload_sha = ledger.sha256_hex(ledger.canonical(payload))
    site = storage.site_url()
    verify_url = f"{site}/verify/{report_id}" if site else f"/verify/{report_id}"
    key = signing.public_key()
    d = placereport.assemble(r, place, frames=frames, heat_image=heat_img, nearby=nearby, payload_sha256=payload_sha,
                             key_fingerprint=key["fingerprint"], verify_url=verify_url, qr_png=_qr(verify_url))
    pdf_bytes = report_pdf.render(d)
    pdf_sha = ledger.sha256_hex(pdf_bytes)
    pdf_url = storage.put_public(f"reports/{report_id}.pdf", pdf_bytes, "application/pdf", immutable=True)
    attestation = {"reportId": report_id, "kind": "place-report", "payloadSha256": payload_sha, "pdfSha256": pdf_sha,
                   "signedAt": store.now_iso(), "keyFingerprint": key["fingerprint"], "issuer": "JalSmriti"}
    canon = ledger.canonical(attestation)
    sig = signing.sign_digest(hashlib.sha256(canon).digest())
    sets = {"status": "ready", "payload": payload, "payloadSha256": payload_sha, "pdfSha256": pdf_sha, "pdfUrl": pdf_url,
            "attestation": attestation, "attestationCanonical": canon.decode("utf-8"), "signature": sig,
            "keyFingerprint": key["fingerprint"], "readyAt": store.now_iso(), "pages": pdf_bytes.count(b"/Type /Page") -
            pdf_bytes.count(b"/Type /Pages")}
    store.update(f"RPT#{report_id}", "META", sets=sets, remove=["error"])
    store.bump_stats(reports=1)
    return {**r, **sets}


def handler(event, context=None):
    failures = []
    for rec in event.get("Records", []):
        msg = json.loads(rec["body"])
        try:
            if msg.get("type") == "dossier":
                build_dossier(msg["dossierId"])
            elif msg.get("type") == "report":
                build_report(msg["reportId"])
        except Exception as ex:
            log.exception("job failed: %s", ex)
            final = int(rec.get("attributes", {}).get("ApproximateReceiveCount", "1")) >= 3   # the queue's maxReceiveCount
            if msg.get("type") == "dossier":
                sets = {"status": "failed", "error": str(ex)[:300]} if final else {"lastError": str(ex)[:300]}
                store.update(f"DOSS#{msg['dossierId']}", "META", sets=sets)
            elif msg.get("type") == "report":
                sets = {"status": "failed", "error": str(ex)[:300]} if final else {"lastError": str(ex)[:300]}
                store.update(f"RPT#{msg['reportId']}", "META", sets=sets)
            # always report it: SQS retries, and after the last attempt moves the message to the dead-letter queue
            failures.append({"itemIdentifier": rec.get("messageId")})
    return {"batchItemFailures": failures}
