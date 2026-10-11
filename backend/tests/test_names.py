"""Water bodies without a name of their own are named after what is near them ("Water body near Bellandur Lake"),
never just "Unnamed water body", and a live area can be re-named in place without reading imagery again."""
import pytest

from jalsmriti import names, storage, store
from jalsmriti.areas import AREAS

BELLANDUR = (12.9352, 77.6640, "Bellandur Lake")
VARTHUR = (12.9416, 77.7393, "Varthur Lake")


def test_direction_is_seen_from_the_anchor():
    lat, lon = 12.935, 77.664
    assert names.direction(lat + 0.01, lon, lat, lon) == "north"
    assert names.direction(lat, lon + 0.01, lat, lon) == "east"
    assert names.direction(lat - 0.007, lon - 0.007, lat, lon) == "south-west"


@pytest.mark.parametrize("where, generated, expect, source", [
    # 600 m north of Bellandur: named after it, whatever the geocoder said
    ((12.9406, 77.6640), {"locality": "Mahadevapura"}, "Water body near Bellandur Lake", "nearby-lake"),
    # 1.5 km east of Bellandur: distance and side
    ((12.9352, 77.6778), None, "Water body 1.5 km east of Bellandur Lake", "nearby-lake"),
    # 4 km from any named lake, with a locality from the geocoder: the locality wins
    ((12.9000, 77.6900), {"locality": "Haralur"}, "Water body near Haralur", "nearby-place"),
    # 4.8 km away and no locality: the nearest lake, with distance and side
    ((12.9000, 77.6900), None, "Water body 4.8 km south-east of Bellandur Lake", "nearby-lake"),
])
def test_fallback_name(where, generated, expect, source):
    f = names.fallback_name(*where, "lake", [BELLANDUR, VARTHUR], [], generated, "Bengaluru")
    assert (f["name"], f["source"]) == (expect, source)


def test_fallback_goes_to_the_locality_of_neighbours_then_the_area():
    places = [(13.10, 77.50, "Yelahanka")]
    f = names.fallback_name(13.11, 77.51, "lake", [BELLANDUR], places, None, "Bengaluru")
    assert (f["name"], f["source"]) == ("Water body in Yelahanka", "nearby-place")
    f = names.fallback_name(13.30, 77.90, "river", [BELLANDUR], places, None, "Bengaluru")
    assert (f["name"], f["source"]) == ("River stretch in Bengaluru", "area")


def test_repeated_names_get_their_side_of_the_lake():
    north = names.fallback_name(12.9406, 77.6640, "lake", [BELLANDUR], [], None, "Bengaluru")
    south = names.fallback_name(12.9300, 77.6640, "lake", [BELLANDUR], [], None, "Bengaluru")
    alone = names.fallback_name(12.9352, 77.6778, "lake", [BELLANDUR], [], None, "Bengaluru")
    names.distinct([north, south, alone])
    assert north["name"] == "Water body north of Bellandur Lake"
    assert south["name"] == "Water body south of Bellandur Lake"
    assert alone["name"] == "Water body 1.5 km east of Bellandur Lake"          # not repeated: unchanged
    a = names.fallback_name(12.9150, 77.7150, "lake", [VARTHUR], [], {"locality": "Haralur"}, "Bengaluru")
    b = names.fallback_name(12.9200, 77.7250, "lake", [VARTHUR], [], {"locality": "Haralur"}, "Bengaluru")
    assert a["name"] == b["name"] == "Water body near Haralur"
    names.distinct([a, b])
    assert (a["name"], b["name"]) == ("Water body 4.0 km south-west of Varthur Lake",
                                      "Water body 2.9 km south-west of Varthur Lake")


def test_rename_updates_a_live_area_in_place(aws):
    import area
    aid = "bengaluru"
    bodies = [
        {"lakeId": "ben-named01", "kind": "lake", "lat": 12.9352, "lon": 77.6640, "areaHa": 300.0},
        {"lakeId": "ben-anon001", "kind": "lake", "lat": 12.9406, "lon": 77.6640, "areaHa": 3.0},
        {"lakeId": "ben-anon002", "kind": "lake", "lat": 12.9300, "lon": 77.6640, "areaHa": 2.5},
        {"lakeId": "ben-river01", "kind": "river", "lat": 12.9352, "lon": 77.6778, "areaHa": 9.0},
    ]
    storage.put_data_json(f"areas/{aid}/base.json", {"bodies": bodies})
    storage.put_data_json(f"areas/{aid}/names.json", {
        "ben-named01": {"name": "Bellandur Lake", "source": "OpenStreetMap", "locality": "Bellandur"},
        "ben-anon001": {"name": "Water body near Mahadevapura", "source": "generated", "locality": "Mahadevapura"}})
    for b in bodies:
        old = "Bellandur Lake" if b["lakeId"] == "ben-named01" else "Unnamed water body"
        store.put({"PK": f"AREA#{aid}", "SK": f"LAKE#{b['lakeId']}", "lakeId": b["lakeId"], "name": old})
        if b["kind"] == "lake":
            store.put({"PK": f"LAKE#{b['lakeId']}", "SK": "META", "lakeId": b["lakeId"], "name": old,
                       "nameSource": "GeoNames/generated"})
    storage.put_public_json(f"areas/{aid}/lakes.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": b["lakeId"], "geometry": None, "properties": {"lakeId": b["lakeId"], "name": "x"}}
        for b in bodies]})

    out = area.rename({"areaId": aid})
    assert out["ok"] and out["renamed"] == 3 and out["sources"]["OpenStreetMap"] == 1
    got = {r["lakeId"]: r["name"] for r in store.query_all(f"AREA#{aid}", "LAKE#ben-")}
    assert got["ben-anon001"] == "Water body north of Bellandur Lake"         # two "near Bellandur" told apart
    assert got["ben-anon002"] == "Water body south of Bellandur Lake"
    assert got["ben-river01"] == "River stretch 1.5 km east of Bellandur Lake"
    meta = store.get("LAKE#ben-anon001")
    assert meta["name"] == got["ben-anon001"] and meta["nameSource"] == "nearby-lake"
    assert store.get("LAKE#ben-named01")["name"] == "Bellandur Lake"
    gj = storage.get_public_json(f"areas/{aid}/lakes.geojson")
    assert {f["properties"]["lakeId"]: f["properties"]["name"] for f in gj["features"]} == {**got, "ben-named01": "Bellandur Lake"}
    assert not any("Unnamed" in n for n in got.values())
    assert area.rename({"areaId": aid})["renamed"] == 0                        # nothing left to change
