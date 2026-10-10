"""Cedar access rules: each policy allows or forbids what it says, and the decision names the policy."""
import pytest

from jalsmriti import authz


def user(sub, groups=(), juris=""):
    claims = {"sub": sub, "email": f"{sub}@example.com"}
    if groups:
        claims["cognito:groups"] = f"[{' '.join(groups)}]"      # how API Gateway passes list claims
    if juris:
        claims["custom:jurisdictions"] = juris
    return authz.user_from_claims(claims)


CITIZEN = user("c-1")
OTHER = user("c-2")
VERIFIER = user("v-1", ["verifier"], "bengaluru,chennai")
OFFICER = user("o-1", ["officer"], "bengaluru")
ADMIN = user("a-1", ["admin"], "*")

LAKE = authz.lake_entity("ben-abc1234", "bengaluru", "lake")
RIVER = authz.lake_entity("ben-riv1234", "bengaluru", "river")
EVIDENCE, EV_STUB = authz.evidence_entity({"evidenceId": "ev-1", "lakeId": "ben-abc1234", "areaId": "bengaluru", "uploaderId": "c-1"})


def dossier(status, creator="c-1", area="bengaluru"):
    return authz.dossier_entity({"dossierId": "ds-1", "lakeId": "ben-abc1234", "areaId": area, "status": status, "creatorId": creator})


def test_roles_and_pseudonyms():
    assert (CITIZEN["role"], VERIFIER["role"], OFFICER["role"], ADMIN["role"]) == ("citizen", "verifier", "officer", "admin")
    assert CITIZEN["pseudonym"].startswith("Citizen ") and VERIFIER["pseudonym"].startswith("Verifier ")
    assert CITIZEN["pseudonym"] == user("c-1")["pseudonym"]            # stable
    assert VERIFIER["jurisdictions"] == ["bengaluru", "chennai"]


@pytest.mark.parametrize("action", ["UploadEvidence", "CreateDossier", "WatchLake"])
def test_any_signed_in_person_can_act_on_a_lake(action):
    d = authz.decision(CITIZEN, action, LAKE)
    assert d["allowed"] and d["policies"]


def test_rivers_take_no_dossiers():
    assert not authz.decision(CITIZEN, "CreateDossier", RIVER)["allowed"]
    assert authz.decision(CITIZEN, "WatchLake", RIVER)["allowed"]


def test_verifier_reviews_in_jurisdiction_with_a_note():
    ok = authz.decision(VERIFIER, "ReviewEvidence", EVIDENCE, {"hasNote": True}, [EV_STUB])
    assert ok["allowed"] and ok["policies"] == ["verifiers-review-in-jurisdiction"]
    no_note = authz.decision(VERIFIER, "ReviewEvidence", EVIDENCE, {"hasNote": False}, [EV_STUB])
    assert not no_note["allowed"] and "10 characters" in no_note["rule"]
    elsewhere, stub = authz.evidence_entity({"evidenceId": "ev-2", "lakeId": "del-x", "areaId": "delhi-ncr", "uploaderId": "c-1"})
    assert not authz.decision(VERIFIER, "ReviewEvidence", elsewhere, {"hasNote": True}, [stub])["allowed"]
    assert not authz.decision(OFFICER, "ReviewEvidence", EVIDENCE, {"hasNote": True}, [EV_STUB])["allowed"]


def test_nobody_verifies_their_own_upload():
    own, stub = authz.evidence_entity({"evidenceId": "ev-3", "lakeId": "ben-abc1234", "areaId": "bengaluru", "uploaderId": "a-1"})
    d = authz.decision(ADMIN, "ReviewEvidence", own, {"hasNote": True}, [stub])
    assert not d["allowed"] and d["policies"] == ["no-self-verification"]


def test_only_the_creator_records_a_submission():
    res, stub = dossier("ready")
    assert authz.decision(CITIZEN, "MarkSubmitted", res, extra=[stub])["allowed"]
    assert not authz.decision(OTHER, "MarkSubmitted", res, extra=[stub])["allowed"]
    assert not authz.decision(VERIFIER, "MarkSubmitted", res, extra=[stub])["allowed"]


def test_officers_respond_only_after_submission_and_in_jurisdiction():
    ready, stub = dossier("ready")
    d = authz.decision(OFFICER, "RespondDossier", ready, {"hasNote": True}, [stub])
    assert not d["allowed"] and d["policies"] == ["respond-only-after-submission"]
    submitted, stub = dossier("submitted")
    assert authz.decision(OFFICER, "RespondDossier", submitted, {"hasNote": True}, [stub])["allowed"]
    chennai, stub = dossier("submitted", area="chennai")
    assert not authz.decision(OFFICER, "RespondDossier", chennai, {"hasNote": True}, [stub])["allowed"]
    assert not authz.decision(VERIFIER, "RespondDossier", submitted, {"hasNote": True}, [stub])["allowed"]


def test_queues_and_audit_logs_are_for_officials_of_the_area():
    blr, del_ = authz.area_entity("bengaluru"), authz.area_entity("delhi-ncr")
    for action in ("ViewQueue", "ViewAudit"):
        assert authz.decision(VERIFIER, action, blr)["allowed"]
        assert authz.decision(OFFICER, action, blr)["allowed"]
        assert authz.decision(ADMIN, action, del_)["allowed"]
        assert not authz.decision(OFFICER, action, del_)["allowed"]
        assert not authz.decision(CITIZEN, action, blr)["allowed"]


def test_evidence_is_never_deleted():
    d = authz.decision(ADMIN, "DeleteEvidence", EVIDENCE, extra=[EV_STUB])
    assert not d["allowed"] and d["policies"] == ["evidence-is-never-deleted"]


def test_every_policy_has_a_plain_rule():
    text = authz.policy_text()
    ids = [line.split('"')[1] for line in text.splitlines() if line.startswith("@id(")]
    assert len(ids) == 16 and set(ids) == set(authz.RULES)


def report(area="bengaluru", reporter="c-1"):
    return authz.report_entity({"reportId": "wl-1", "areaId": area, "status": "live", "uploaderId": reporter})


def test_anyone_signed_in_follows_places_and_reports_standing_water():
    for action in ("FollowPlace", "ReportWaterlogging"):
        for area in ("bengaluru", "other"):
            d = authz.decision(CITIZEN, action, authz.area_entity(area))
            assert d["allowed"] and d["policies"]


def test_rti_requests_are_recorded_for_lakes_not_rivers():
    assert authz.decision(CITIZEN, "RecordRti", LAKE)["policies"] == ["citizens-record-rti"]
    assert not authz.decision(CITIZEN, "RecordRti", RIVER)["allowed"]


def test_verifiers_review_water_reports_in_their_areas_with_a_note():
    res, stub = report()
    d = authz.decision(VERIFIER, "ReviewReport", res, {"hasNote": True}, [stub])
    assert d["allowed"] and d["policies"] == ["verifiers-review-water-reports"]
    assert not authz.decision(VERIFIER, "ReviewReport", res, {"hasNote": False}, [stub])["allowed"]
    far, stub2 = report(area="delhi-ncr")
    assert not authz.decision(VERIFIER, "ReviewReport", far, {"hasNote": True}, [stub2])["allowed"]
    assert not authz.decision(OFFICER, "ReviewReport", res, {"hasNote": True}, [stub])["allowed"]
    assert not authz.decision(CITIZEN, "ReviewReport", res, {"hasNote": True}, [stub])["allowed"]


def test_nobody_reviews_their_own_water_report():
    own, stub = report(reporter="a-1")
    d = authz.decision(ADMIN, "ReviewReport", own, {"hasNote": True}, [stub])
    assert not d["allowed"] and d["policies"] == ["no-self-review-of-water-reports"]
