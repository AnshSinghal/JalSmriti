"""Evidence ingest: S3 upload -> SQS -> this function (provenance, privacy, relevance, triage, ledger).

Lake photos (evidence/<lake>/<id>) go into the lake's evidence and ledger, unless they are not photos of the place at
all (a screenshot, document, poster or indoor photo: status "unrelated", kept private with the reason, never in the
ledger); waterlogging photos (evidence/waterlogging/<wl...>) become standing-water reports on the live map
(jalsmriti.waterlog).
"""
from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse

from jalsmriti import evidence as E
from jalsmriti import ledger, storage, store, waterlog
from jalsmriti import config as C

log = logging.getLogger()
log.setLevel(logging.INFO)


def process(evidence_id: str, data: bytes) -> dict:
    if evidence_id.startswith("wl"):
        return waterlog.process(evidence_id, data)
    ev = store.get(f"EVID#{evidence_id}")
    if not ev:
        raise ValueError(f"unknown evidence {evidence_id}")
    if ev.get("status") not in ("uploading", None):
        return ev                                    # already processed (SQS delivers at least once)
    sha = hashlib.sha256(data).hexdigest()
    exif = E.read_exif(data)
    lake = store.get(f"LAKE#{ev['lakeId']}") or {}
    gps_check, dist = "none", None
    if exif.get("lat") is not None and lake.get("geometry"):
        dist = E.distance_to_outline_m(exif["lat"], exif["lon"], lake["geometry"])
        gps_check = "inside" if dist <= 30 else "near" if dist <= C.EVIDENCE_GEOFENCE_M else "far"
    model_jpeg = E.jpeg_for_models(data)
    mod = E.moderate(model_jpeg)
    sets = {"sha256": sha, "exif": {k: v for k, v in exif.items() if k not in ("lat", "lon")},
            "gps": {"lat": round(exif["lat"], 6), "lon": round(exif["lon"], 6)} if exif.get("lat") is not None else None,
            "gpsCheck": gps_check, "gpsDistanceM": round(dist) if dist is not None else None,
            "capturedAt": exif.get("capturedAt"), "moderation": mod, "processedAt": store.now_iso(), "bytes": len(data)}
    who = {"id": ev["uploaderId"], "pseudonym": ev.get("uploader")}
    if mod["blocked"]:
        sets.update(status="blocked", GSI3SK=f"blocked#{ev['createdAt']}")
        store.update(f"EVID#{evidence_id}", "META", sets=sets)
        store.audit(ev.get("areaId"), who, "EvidenceBlocked", {"evidenceId": evidence_id},
                    extra={"labels": mod["labels"][:5]})
        return {**ev, **sets}
    lbls = E.labels(model_jpeg)
    words = E.text_words(model_jpeg)
    tri = E.triage(model_jpeg)
    sets.update(labels=lbls[:12], ai=tri, textWords=words)
    reason = E.relevance(tri, words, lbls)
    if reason:                                       # not a photo of the place: kept private, with the reason
        sets.update(status="unrelated", unrelatedReason=reason, GSI3SK=f"unrelated#{ev['createdAt']}")
        store.update(f"EVID#{evidence_id}", "META", sets=sets)
        store.audit(ev.get("areaId"), who, "EvidenceUnrelated", {"evidenceId": evidence_id},
                    extra={"reason": reason, "scene": tri.get("scene"), "words": words,
                           "labels": [l["name"] for l in lbls[:6]]})
        return {**ev, **sets}
    face_boxes = E.faces(model_jpeg)
    cats = tri.get("categories") or E.categories_from_labels(lbls) or ["other"]
    big, thumb, size = E.public_copies(data, face_boxes)
    url = storage.put_public(f"evidence/{ev['lakeId']}/{evidence_id}.jpg", big, "image/jpeg", immutable=True)
    turl = storage.put_public(f"evidence/{ev['lakeId']}/{evidence_id}_t.jpg", thumb, "image/jpeg", immutable=True)
    entry = ledger.append(ev["lakeId"], "evidence", evidence_id,
                          ledger.sha256_hex(ledger.canonical({"evidenceId": evidence_id, "sha256": sha, "gps": sets["gps"],
                                                              "capturedAt": exif.get("capturedAt"), "uploadedAt": ev["createdAt"]})),
                          ev.get("uploader", "citizen"))
    sets.update(status="new", url=url, thumbUrl=turl, width=size[0], height=size[1], facesBlurred=len(face_boxes),
                categories=cats, ledgerSeq=entry["seq"], ledgerHash=entry["hash"], GSI3SK=f"new#{ev['createdAt']}")
    store.update(f"EVID#{evidence_id}", "META", sets=sets)
    store.update(f"LAKE#{ev['lakeId']}", "META", adds={"evidenceCount": 1})
    store.bump_stats(evidence=1)
    return {**ev, **sets}


AUTO_CHECK = "Automatic photo check"
EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def recheck(area_id: str | None = None, cap: int = 300) -> dict:
    """Run today's photo checks on photos that are still awaiting review and were checked before they existed.

    A photo that is not of the place is already in its lake's ledger, so it is withdrawn on the record: a review
    entry by the automatic check, with the reason, goes into the ledger; the public copies are deleted and the photo
    leaves the lake's page. Photos that pass keep their place and get the newer AI description. Run by deploy.py
    after an update (a direct invocation: {"maintenance": "recheck-evidence"})."""
    from jalsmriti import areas as A
    checked, withdrawn = 0, []
    for area in ([area_id] if area_id else [*A.AREAS, "other"]):
        for ev in store.query_all(f"QUEUE#EVID#{area}", "new#", index="GSI3", cap=cap):
            if "textWords" in ev or ev.get("status") != "new":
                continue                                       # checked by today's code already
            eid, lake_id = ev["evidenceId"], ev["lakeId"]
            try:
                data = storage.get_data(f"evidence/{lake_id}/{eid}.{EXT.get(ev.get('contentType'), 'jpg')}")
                jpeg = E.jpeg_for_models(data)
            except Exception as ex:
                log.warning("recheck %s: original not readable: %s", eid, ex)
                continue
            lbls, words, tri = E.labels(jpeg), E.text_words(jpeg), E.triage(jpeg)
            checked += 1
            reason = E.relevance(tri, words, lbls)
            sets = {"labels": lbls[:12], "ai": tri, "textWords": words}
            if not reason:
                store.update(f"EVID#{eid}", "META", sets=sets)
                continue
            rv = {"decision": "unrelated", "by": AUTO_CHECK, "role": "system", "at": store.now_iso(),
                  "note": f"Not a photo of the lake ({reason})" + (f": {tri['summary']}" if tri.get("summary") else "")}
            entry = ledger.append(lake_id, "review", eid, ledger.sha256_hex(ledger.canonical(rv)), AUTO_CHECK)
            store.update(f"EVID#{eid}", "META", remove=["url", "thumbUrl"],
                         sets={**sets, "status": "unrelated", "unrelatedReason": reason,
                               "review": {**rv, "ledgerSeq": entry["seq"]}, "GSI3SK": f"unrelated#{ev['createdAt']}"})
            for suffix in ("", "_t"):
                try:
                    storage.delete_public(f"evidence/{lake_id}/{eid}{suffix}.jpg")
                except Exception as ex:
                    log.warning("recheck %s: public copy not deleted: %s", eid, ex)
            store.update(f"LAKE#{lake_id}", "META", adds={"evidenceCount": -1})
            store.audit(ev.get("areaId"), {"id": "system", "pseudonym": AUTO_CHECK, "role": "system"},
                        "EvidenceUnrelated", {"evidenceId": eid},
                        extra={"reason": reason, "scene": tri.get("scene"), "words": words, "recheck": True})
            withdrawn.append({"evidenceId": eid, "lakeId": lake_id, "reason": reason})
    return {"checked": checked, "withdrawn": withdrawn}


def handler(event, context=None):
    """SQS batch of S3 event notifications; failed records are returned for retry (partial batch response).
    A direct invocation {"maintenance": "recheck-evidence"} runs recheck() instead."""
    if event.get("maintenance") == "recheck-evidence":
        return recheck(event.get("area"))
    failures = []
    for rec in event.get("Records", []):
        try:
            body = json.loads(rec["body"])
            if body.get("Event") == "s3:TestEvent":
                continue
            for s3r in body.get("Records", []):
                key = urllib.parse.unquote_plus(s3r["s3"]["object"]["key"])
                if not key.startswith("evidence/"):
                    continue
                evidence_id = key.rsplit("/", 1)[-1].split(".")[0]
                data = storage.get_data(key)
                process(evidence_id, data)
        except Exception as ex:
            log.exception("evidence ingest failed: %s", ex)
            failures.append({"itemIdentifier": rec.get("messageId")})
    return {"batchItemFailures": failures}
