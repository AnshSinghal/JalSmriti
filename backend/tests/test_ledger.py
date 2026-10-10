"""The per-lake hash chain: appends link up, and any edit to the past is detected."""
from jalsmriti import ledger, store


def test_chain_appends_and_verifies(aws):
    lake = "t-" + store.new_id()[-8:]
    a = ledger.append(lake, "evidence", "ev-1", ledger.sha256_hex(b"photo"), "Citizen 0001")
    b = ledger.append(lake, "review", "ev-1", ledger.sha256_hex(b"ok"), "Verifier 0002")
    assert (a["seq"], b["seq"]) == (1, 2)
    assert a["prevHash"] == ledger.GENESIS and b["prevHash"] == a["hash"]
    v = ledger.verify(lake)
    assert v == {"ok": True, "entries": 2, "head": b["hash"]}


def test_editing_an_entry_breaks_the_chain(aws):
    lake = "t-" + store.new_id()[-8:]
    for i in range(3):
        ledger.append(lake, "evidence", f"ev-{i}", ledger.sha256_hex(str(i).encode()), "Citizen 0001")
    store.update(f"LEDGER#{lake}", "00000002", sets={"actor": "Someone else"})
    v = ledger.verify(lake)
    assert not v["ok"] and v["brokenAt"] == 2


def test_canonical_json_is_stable():
    # the same facts hash the same whatever the key order or float noise from a DynamoDB round trip
    assert ledger.canonical({"b": 27.0, "a": [1.0000001]}) == ledger.canonical({"a": [1], "b": 27})
    assert ledger.canonical({"x": None}) == b"{}"
