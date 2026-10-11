"""Is an upload a photo of the place at all? A screenshot, document, poster or indoor photo is kept private as
"unrelated" with its reason: never on the lake's page, in its ledger or in the verifiers' queue. Rekognition's word
count and labels and Amazon Nova's own answer are checked independently; photos checked before this existed are
re-checked and withdrawn on the record."""
import pytest

from jalsmriti import evidence as E
from jalsmriti import ledger, storage, store
from test_api import CITIZEN, VERIFIER, call, photo


def L(*names, conf=95.0):
    return [{"name": n, "confidence": conf} for n in names]


NOVA_NOT_SITE = {"sitePhoto": False, "confidence": 0.95, "scene": "poster_or_graphic", "categories": [],
                 "summary": "An infographic about a data breach at an AI company.", "model": "test"}
NOVA_SITE = {"sitePhoto": True, "confidence": 0.9, "scene": "lake_or_pond", "categories": ["dumping"],
             "summary": "Plastic waste on the bund of a lake.", "model": "test"}
NOVA_DOWN = {"sitePhoto": None, "confidence": None, "scene": None, "categories": [], "summary": None, "model": None}


@pytest.mark.parametrize("tri, words, labels, reason", [
    # the breach infographic: many printed words, a made image, nothing outdoors
    (NOVA_DOWN, 60, L("Poster", "Advertisement", "Text"), "text"),
    (NOVA_NOT_SITE, 60, L("Poster", "Advertisement", "Text"), "text"),
    # even when Nova is fooled, many words and no outdoor scene is not a site photo
    (NOVA_SITE, 80, L("Text", "Document", "Page"), "text"),
    # a long notice board at the lake: many words, but outdoors and Nova says it is the place
    (NOVA_SITE, 45, L("Outdoors", "Tree", "Text", "Sign"), None),
    # a drawing or cartoon with few words
    (NOVA_DOWN, 4, L("Drawing", "Art", "Cartoon"), "graphic"),
    # Nova sure it is indoors
    ({**NOVA_NOT_SITE, "scene": "indoor"}, 0, L("Indoors", "Furniture", "Room"), "indoor"),
    # Nova sure it is not the place, no particular scene
    ({**NOVA_NOT_SITE, "scene": "other"}, 0, L("Person", "Face", "Smile"), "other"),
    # Nova says no, but Rekognition sees water: two models disagree, a verifier decides
    ({**NOVA_NOT_SITE, "scene": "other"}, 0, L("Water", "Outdoors"), None),
    # Nova unsure
    ({**NOVA_NOT_SITE, "confidence": 0.4, "scene": "other"}, 0, L("Outdoors"), None),
    # a lake photo
    (NOVA_SITE, 0, L("Water", "Lake", "Outdoors", "Garbage"), None),
    # nothing answered: no reason to refuse
    (NOVA_DOWN, None, [], None),
])
def test_relevance(tri, words, labels, reason):
    assert E.relevance(tri, words, labels) == reason


def test_weak_labels_do_not_count():
    # an "Outdoors" Rekognition is only 60% sure of does not save a screenshot
    assert E.relevance(NOVA_DOWN, 30, L("Text", conf=99) + L("Outdoors", conf=60)) == "text"
    assert E.relevance(NOVA_DOWN, 30, L("Text", conf=99) + L("Outdoors", conf=90)) is None


def test_text_words_counts_confident_words(monkeypatch):
    calls = []

    class Rek:
        def detect_text(self, **kw):
            calls.append(kw)
            return {"TextDetections": [
                {"Type": "LINE", "DetectedText": "HUGGING FACE BREACH", "Confidence": 99.0},
                *[{"Type": "WORD", "DetectedText": f"w{i}", "Confidence": 97.0} for i in range(30)],
                {"Type": "WORD", "DetectedText": "blur", "Confidence": 50.0}]}

    monkeypatch.setattr(E.C, "LOCAL", False)
    monkeypatch.setattr(E, "_rek", lambda: Rek())
    assert E.text_words(b"jpeg") == 30
    assert calls[0]["Filters"] == {"WordFilter": {"MinConfidence": E.TEXT_MIN_CONFIDENCE}}

    class Down:
        def detect_text(self, **kw):
            raise RuntimeError("AccessDeniedException")
    monkeypatch.setattr(E, "_rek", lambda: Down())
    assert E.text_words(b"jpeg") is None                  # the other signals still decide


def test_triage_reads_novas_answer(monkeypatch):
    from jalsmriti import bedrock
    monkeypatch.setattr(E.C, "LOCAL", False)
    seen = {}

    def fake(prompt, image, fmt="jpeg", **kw):
        seen["prompt"] = prompt
        return ('{"scene": "poster_or_graphic", "site_photo": "false", "confidence": 95, '
                '"categories": ["dead_fish", "dumping"], "summary": "  An infographic   about a breach. ", '
                '"water_visible": false}'), "apac.amazon.nova-lite-v1:0"
    monkeypatch.setattr(bedrock, "converse_image", fake)
    tri = E.triage(b"jpeg")
    assert "never assume that a lake is there" in seen["prompt"] and "screenshot_or_document" in seen["prompt"]
    assert tri == {"categories": [], "summary": "An infographic about a breach.", "waterVisible": False,
                   "confidence": 0.95, "sitePhoto": False, "scene": "poster_or_graphic",
                   "model": "apac.amazon.nova-lite-v1:0"}

    monkeypatch.setattr(bedrock, "converse_image", lambda *a, **k: (
        '{"scene": "lake_or_pond", "site_photo": true, "confidence": 0.8, "categories": ["weeds", "other", "x"], '
        '"summary": "Water hyacinth covers the lake.", "water_visible": true}', "m"))
    tri = E.triage(b"jpeg")
    assert tri["categories"] == ["weeds"] and tri["sitePhoto"] is True and tri["scene"] == "lake_or_pond"


def upload(lid, who=CITIZEN):
    s, up = call("POST", f"/v1/secure/lakes/{lid}/evidence/upload", {"contentType": "image/jpeg", "size": 50_000}, who)
    assert s == 200
    return up["evidenceId"]


def test_unrelated_upload_stays_private(aws, lake, monkeypatch):
    import evidence_ingest
    lid = lake["lakeId"]
    monkeypatch.setattr(E, "labels", lambda jpeg: L("Poster", "Advertisement", "Text"))
    monkeypatch.setattr(E, "text_words", lambda jpeg: 64)
    monkeypatch.setattr(E, "triage", lambda jpeg: dict(NOVA_NOT_SITE))
    before = len(ledger.entries(lid))
    eid = upload(lid)
    ev = evidence_ingest.process(eid, photo(12.935, 77.665))
    assert ev["status"] == "unrelated" and ev["unrelatedReason"] == "text" and ev["GSI3SK"].startswith("unrelated#")
    assert not {"url", "thumbUrl", "ledgerSeq"} & set(ev)
    assert len(ledger.entries(lid)) == before                                  # not in the lake's record
    assert not storage.exists("site", f"pub/evidence/{lid}/{eid}.jpg")
    assert eid not in [e["evidenceId"] for e in call("GET", f"/v1/lakes/{lid}/evidence")[1]["evidence"]]
    s, mine = call("GET", f"/v1/secure/evidence/{eid}", who=CITIZEN)           # the uploader sees why
    assert s == 200 and mine["status"] == "unrelated" and mine["unrelatedReason"] == "text"
    assert mine["ai"]["summary"] == NOVA_NOT_SITE["summary"] and mine["textWords"] == 64
    s, q = call("GET", "/v1/secure/console/queue", who=VERIFIER, query={"area": "bengaluru", "type": "evidence"})
    assert eid not in [i["evidenceId"] for i in q["items"]]                   # nothing for verifiers to do
    s, _ = call("POST", f"/v1/secure/evidence/{eid}/review", {"decision": "verified", "note": "Looks fine to me."}, VERIFIER)
    assert s == 404
    audit = store.query_all("AUDIT#bengaluru")
    assert any(a["action"] == "EvidenceUnrelated" and a["resource"] == {"evidenceId": eid}
               and a["extra"]["reason"] == "text" for a in audit)


def test_lake_photo_still_goes_to_the_verifier(aws, lake, monkeypatch):
    import evidence_ingest
    lid = lake["lakeId"]
    monkeypatch.setattr(E, "labels", lambda jpeg: L("Water", "Outdoors", "Garbage"))
    monkeypatch.setattr(E, "text_words", lambda jpeg: 3)
    monkeypatch.setattr(E, "triage", lambda jpeg: dict(NOVA_SITE))
    ev = evidence_ingest.process(upload(lid), photo(12.935, 77.665))
    assert ev["status"] == "new" and ev["categories"] == ["dumping"] and ev["ledgerSeq"] >= 1
    assert ev["textWords"] == 3 and ev["ai"]["sitePhoto"] is True


def test_recheck_withdraws_old_unrelated_photos_on_the_record(aws, lake, monkeypatch):
    import evidence_ingest
    lid = lake["lakeId"]
    # two photos checked by the old code (no text check): an infographic and a real lake photo
    eids = [upload(lid), upload(lid)]
    for eid in eids:
        evidence_ingest.process(eid, photo(12.935, 77.665))
        store.update(f"EVID#{eid}", "META", remove=["textWords"])
        storage.put_data(f"evidence/{lid}/{eid}.jpg", photo(12.935, 77.665))
    bad, good = eids
    assert storage.exists("site", f"pub/evidence/{lid}/{bad}.jpg")
    seq_before = len(ledger.entries(lid))
    count_before = store.get(f"LAKE#{lid}")["evidenceCount"]

    def look(jpeg, _n=iter(range(10))):
        return dict(NOVA_NOT_SITE) if next(_n) == 0 else dict(NOVA_SITE)
    monkeypatch.setattr(E, "triage", look)
    monkeypatch.setattr(E, "labels", lambda jpeg: [])
    monkeypatch.setattr(E, "text_words", lambda jpeg: 0)
    out = evidence_ingest.handler({"maintenance": "recheck-evidence", "area": "bengaluru"})
    assert out["checked"] == 2 and out["withdrawn"] == [{"evidenceId": bad, "lakeId": lid, "reason": "graphic"}]

    gone = store.get(f"EVID#{bad}")
    assert gone["status"] == "unrelated" and "url" not in gone and gone["review"]["by"] == evidence_ingest.AUTO_CHECK
    assert not storage.exists("site", f"pub/evidence/{lid}/{bad}.jpg")
    assert not storage.exists("site", f"pub/evidence/{lid}/{bad}_t.jpg")
    entries = ledger.entries(lid)
    assert len(entries) == seq_before + 1 and entries[-1]["kind"] == "review" and entries[-1]["subjectId"] == bad
    assert ledger.verify(lid)["ok"]
    assert store.get(f"LAKE#{lid}")["evidenceCount"] == count_before - 1
    kept = store.get(f"EVID#{good}")
    assert kept["status"] == "new" and kept["ai"]["sitePhoto"] is True and kept["textWords"] == 0
    # a second run has nothing left to do
    assert evidence_ingest.handler({"maintenance": "recheck-evidence", "area": "bengaluru"})["checked"] == 0
