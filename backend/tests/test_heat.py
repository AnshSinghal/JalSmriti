"""Summer heat: temperatures, cloud masking, the composite, the numbers people see and the map image.

Everything here uses made-up arrays; the satellite catalogue and the raster reader are replaced, so nothing touches
the network."""
import io
import json
import math
from datetime import date

import numpy as np
import pytest
from PIL import Image
from rasterio.warp import transform as warp_transform

from jalsmriti import catalog, geo, heat, landcover


# ------------------------------------------------------------------------------------------ temperature and clouds
def test_celsius_from_st_b10_digital_numbers():
    dn = np.array([(300.0 - 149.0) / 0.00341802, 0, np.nan])       # kelvin = DN x 0.00341802 + 149
    t = heat.celsius(dn)
    assert t.dtype == np.float32
    assert t[0] == pytest.approx(26.85, abs=1e-3)
    assert np.isnan(t[1]) and np.isnan(t[2])                        # DN 0 is "no data", not -124 C


def test_implausible_temperatures_are_not_used():
    t = np.array([4.9, 5.0, 40.0, 75.0, 75.1, np.nan])
    assert heat.plausible(t).tolist() == [False, True, True, True, False, False]


def test_clear_mask_matches_water_landsat_pass_for_every_qa_value():
    qa = np.arange(65536, dtype=np.uint16)
    fill = (qa & 1).astype(bool) | (qa == 0)                        # the test in water.landsat_pass
    cloudish = (((qa >> 1) & 1) | ((qa >> 2) & 1) | ((qa >> 3) & 1) | ((qa >> 4) & 1)).astype(bool)
    assert np.array_equal(heat.clear_mask(qa), ~fill & ~cloudish)
    # real Landsat 8/9 values: clear land, clear water | high cloud, dilated cloud, fill, outside the scene
    assert heat.clear_mask(np.array([21824, 21952])).all()
    assert not heat.clear_mask(np.array([22280, 21762, 1, 0])).any()


def test_composite_is_the_median_of_clear_observations_and_needs_two():
    stack = np.array([[[30.0, 30.0, 30.0, np.nan]],
                      [[40.0, 40.0, 99.0, 35.0]],
                      [[50.0, 10.0, 41.0, 36.0]]], dtype=np.float32)          # 3 passes of a 1 x 4 grid
    clear = np.array([[[True, True, False, True]],
                      [[True, True, False, True]],
                      [[True, False, True, False]]])
    comp = heat.composite(stack, clear)
    assert comp.dtype == np.float32 and comp.shape == (1, 4)
    assert comp[0, 0] == 40                         # median of 30, 40, 50
    assert comp[0, 1] == 35                         # the cloudy 10 is ignored: median of 30, 40
    assert np.isnan(comp[0, 2])                     # one clear observation is not enough
    assert np.isnan(comp[0, 3])                     # a clear flag on a missing temperature does not count
    assert heat.composite(stack, clear, min_obs=1)[0, 2] == 41


# ------------------------------------------------------------------------------------------ grid and statistics
def test_grid_is_6_km_at_30_m_on_the_ground_and_the_disk_is_300_m():
    lat, lon = 28.42, 77.107
    g = heat.heat_grid(lat, lon)
    assert g.shape == (200, 200)
    assert g.res * math.cos(math.radians(lat)) == pytest.approx(30.0)        # Mercator metres -> ground metres
    w, s, e, n = g.bbox_lonlat()
    assert geo.haversine_m(lat, w, lat, e) == pytest.approx(6000, rel=0.01)
    assert geo.haversine_m(s, lon, n, lon) == pytest.approx(6000, rel=0.01)
    l, b, r, t = g.bounds
    xs, ys = warp_transform(g.crs, "EPSG:4326", [(l + r) / 2], [(b + t) / 2])
    assert (xs[0], ys[0]) == pytest.approx((lon, lat), abs=1e-6)              # the point is the grid centre
    disk = heat.disk_mask(g.shape, heat.RADIUS_M / heat.RES_M)
    assert disk.sum() * 30.0 ** 2 == pytest.approx(math.pi * 300.0 ** 2, rel=0.03)
    assert disk[99, 99] and disk[100, 100] and not disk[99, 111] and not disk[0, 0]


def _place(here=44.0, built=42.0, water=30.0, trees=35.0, n_water=25, n_trees=60):
    """A 200 x 200 composite at 40 C with a 300 m 'here' disk, a built-up strip, a pond and a grove."""
    comp = np.full((200, 200), 40.0, dtype=np.float32)
    masks = {k: np.zeros(comp.shape, dtype=bool) for k in ("built", "water", "trees")}
    masks["here"] = heat.disk_mask(comp.shape, 10)              # rows 89-110: clear of the others
    masks["built"][:50, :] = True
    rr, cc = np.divmod(np.arange(100), 10)                      # pixels of a 10 x 10 block, row by row
    masks["water"][150 + rr[:n_water], cc[:n_water]] = True
    masks["trees"][170 + rr[:n_trees], cc[:n_trees]] = True
    for k, v in (("here", here), ("built", built), ("water", water), ("trees", trees)):
        comp[masks[k]] = v
    return comp, masks


def test_stats_compare_here_with_built_up_water_and_trees():
    comp, m = _place()
    s = heat.stats_from(comp, m["here"], m["built"], m["water"], m["trees"])
    assert s == {"hereC": 44.0, "builtC": 42.0, "waterC": 30.0, "treesC": 35.0, "vsBuiltC": 2.0, "vsWaterC": 14.0,
                 "hotter": True}                     # exactly 2 degrees hotter than built-up ground counts
    assert type(s["hereC"]) is float and type(s["hotter"]) is bool
    json.dumps(s)


def test_stats_round_to_a_tenth_and_differences_add_up():
    comp, m = _place(here=41.26, built=39.24)
    s = heat.stats_from(comp, m["here"], m["built"], m["water"], m["trees"])
    assert (s["hereC"], s["builtC"], s["vsBuiltC"], s["hotter"]) == (41.3, 39.2, 2.1, True)


def test_too_few_pixels_give_none_rather_than_a_guess():
    comp, m = _place(n_water=19, n_trees=49)
    s = heat.stats_from(comp, m["here"], m["built"], m["water"], m["trees"])
    assert s["waterC"] is None and s["vsWaterC"] is None and s["treesC"] is None
    assert s["hereC"] == 44.0 and s["builtC"] == 42.0

    comp[m["here"]] = np.nan
    comp[99, 95:104] = 44.0                          # only 9 usable pixels within 300 m
    s = heat.stats_from(comp, m["here"], m["built"], m["water"], m["trees"])
    assert s["hereC"] is None and s["vsBuiltC"] is None and s["hotter"] is None
    comp[99, 104] = 44.0                             # 10 are enough
    assert heat.stats_from(comp, m["here"], m["built"], m["water"], m["trees"])["hereC"] == 44.0

    s = heat.stats_from(comp, m["here"], None, None, None)       # land cover could not be read
    assert s["builtC"] is None and s["waterC"] is None and s["treesC"] is None and s["hotter"] is None


# ------------------------------------------------------------------------------------------ image
def test_colour_scale_widens_in_5_degree_steps():
    assert heat.scale_for(np.linspace(30, 45, 1000)) == (25, 50)
    assert heat.scale_for(np.linspace(30, 53, 1000)) == (25, 55)       # 98th percentile 52.5
    assert heat.scale_for(np.linspace(18, 40, 1000)) == (15, 50)       # 2nd percentile 18.4
    outliers = np.concatenate([np.linspace(30, 45, 990), np.full(10, 70.0)])
    assert heat.scale_for(outliers) == (25, 50)                         # 1 % of hot pixels do not stretch it
    assert heat.scale_for(np.full((3, 3), np.nan)) == (25, 50)


def test_colours_run_cool_to_hot_and_no_data_is_transparent():
    comp = np.array([[25.0, 31.25, 37.5, 43.75, 50.0, 10.0, 90.0, np.nan]])
    rgba = heat.colourise(comp, 25, 50)
    assert rgba.dtype == np.uint8 and rgba.shape == (1, 8, 4)
    assert ["#%02x%02x%02x" % tuple(px[:3]) for px in rgba[0, :5]] == list(heat.PALETTE)
    assert (rgba[0, 5, :3] == rgba[0, 0, :3]).all() and (rgba[0, 6, :3] == rgba[0, 4, :3]).all()   # clipped
    assert rgba[0, :7, 3].tolist() == [255] * 7 and rgba[0, 7, 3] == 0


def test_ring_is_thin_and_centred():
    m = heat.ring_mask((101, 101), 20, 2.0)
    assert m[50, 50] == 0 and m[0, 0] == 0
    assert m[50, 70] == 1 and m[50, 30] == 1 and m[30, 50] == 1 and m[70, 50] == 1
    assert m[50, 50:].sum() == pytest.approx(2.0)          # 2 px wide along a radius


def test_image_is_480_px_with_the_ring_and_transparent_no_data():
    comp = np.full((200, 200), 30.0, dtype=np.float32)
    comp[:, 150:] = 48.0
    comp[:40, :40] = np.nan
    rgba = heat.heat_rgba(comp, 25, 50, radius_px=10)
    assert rgba.shape == (480, 480, 4) and rgba.dtype == np.uint8
    assert rgba[20, 20, 3] == 0                                               # no data stays transparent
    assert (rgba[240, 240] == heat.colourise(np.array([[30.0]]), 25, 50)[0, 0]).all()
    assert (rgba[240, 470] == heat.colourise(np.array([[48.0]]), 25, 50)[0, 0]).all()
    # 300 m = 10 grid px = 24 image px from the centre (239.5, 239.5): white on the ring, dark on both sides
    assert rgba[240, 263].tolist() == [255, 255, 255, 255]
    assert rgba[240, 262, :3].max() <= 40 and rgba[240, 265, :3].max() <= 40
    data = heat.to_webp(rgba)
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    img = Image.open(io.BytesIO(data))
    assert img.size == (480, 480) and img.mode == "RGBA"
    assert np.asarray(img)[20, 20, 3] == 0 and np.asarray(img)[240, 240, 3] == 255   # alpha survives encoding


# ------------------------------------------------------------------------------------------ summers and passes
def test_a_summer_counts_once_june_has_come():
    assert heat.summer_years(date(2026, 10, 11)) == [2024, 2025, 2026]
    assert heat.summer_years(date(2026, 5, 31)) == [2023, 2024, 2025]
    assert heat.summer_years(date(2026, 6, 1)) == [2024, 2025, 2026]


def _item(item_id, day, platform="landsat-8", cloud=1.0, assets=("qa_pixel", "lwir11")):
    return {"id": item_id, "properties": {"datetime": f"{day}T05:10:00Z", "platform": platform, "eo:cloud_cover": cloud},
            "assets": {k: {"href": f"https://example.test/{item_id}/{k}.tif"} for k in assets}}


def test_rows_of_one_pass_are_grouped_and_passes_ranked_by_cloud():
    items = [_item("A1", "2025-04-20", cloud=12.0), _item("A2", "2025-04-20", cloud=3.0),   # one pass, two rows
             _item("B", "2025-04-28", "landsat-9", cloud=0.0),
             _item("C", "2025-04-21", "landsat-7", cloud=0.0),                               # Landsat 7 is not used
             _item("D", "2025-05-06", cloud=0.0, assets=("qa_pixel", "red")),                 # no temperature band
             _item("E", "2025-04-04", cloud=20.0)]
    ps = heat.group_passes(items)
    assert [(str(p["date"]), p["platform"], [r["id"] for r in p["rows"]]) for p in ps] == [
        ("2025-04-28", "landsat-9", ["B"]), ("2025-04-20", "landsat-8", ["A1", "A2"]), ("2025-04-04", "landsat-8", ["E"])]


def test_equally_clear_passes_take_turns_across_summers_and_centre_on_the_season():
    items = [_item(f"{y}-{md}", f"{y}-{md}", cloud=0.0) for y in (2024, 2025, 2026) for md in ("03-20", "04-22", "05-30")]
    ps = heat.group_passes(items)
    assert sorted(str(p["date"]) for p in ps[:3]) == ["2024-04-22", "2025-04-22", "2026-04-22"]
    assert {p["date"].year for p in ps[3:6]} == {2024, 2025, 2026}
    assert heat.group_passes([_item("cloudy", "2026-04-22", cloud=25.0), *items[:1]])[0]["rows"][0]["id"] == "2024-03-20"


def test_pick_keeps_the_clearest_passes_read_in_reading_order():
    d = date(2025, 4, 1)
    fracs = [0.97, 0.39, 0.5, 1.0, 0.91, 0.99, 0.98, 0.96, 0.93, 0.94]
    reads = [None, {"date": d, "usable": None, "clearFrac": 0.1},             # unreadable; skipped as cloudy
             *({"date": d, "usable": np.ones(1, bool), "clearFrac": f, "n": i} for i, f in enumerate(fracs))]
    kept = heat.pick_passes(reads)
    assert [r["n"] for r in kept] == [0, 3, 5, 6, 7, 4, 8, 9]      # 100 % then 90 % (to 10 %), each in reading order
    assert heat.pick_passes(reads[:2]) == []


# ------------------------------------------------------------------------------------------ the whole measurement
LAT, LON = 12.9352, 77.6807


def _dn(temp_c):
    return (np.asarray(temp_c, dtype=np.float64) + 273.15 - 149.0) / 0.00341802


@pytest.fixture()
def world(monkeypatch):
    """A made-up place and satellite: one clear pass per summer day listed in world['days'] (edit it in a test)."""
    w = {"days": ["2024-04-20", "2025-04-22", "2026-04-25"], "cloudy": set(), "unreadable": set(), "land_fails": False,
         "reads": []}
    comp, m = _place()

    def search(api, collection, bbox, dt=None, query=None, **kw):
        a, _, b = dt.partition("/")
        return [_item(f"LC08_{d}", d, cloud=2.0) for d in w["days"] if a <= d <= b]

    def read_mosaic(hrefs, grid, **kw):
        assert grid.shape == (200, 200) and kw.get("use_overviews") is False
        day = hrefs[0].split("/")[3][5:]
        w["reads"].append((day, hrefs[0].rsplit("/", 1)[1]))
        if day in w["unreadable"]:
            raise RuntimeError("could not read: HTTP 503")
        if hrefs[0].endswith("qa_pixel.tif"):
            return np.full(grid.shape, 22280 if day in w["cloudy"] else 21824, dtype=np.uint16)
        return _dn(comp).astype(np.float32)

    def io_lulc(grid, years):
        if w["land_fails"]:
            raise RuntimeError("could not read land cover")
        return {years[0]: np.where(m["built"], 7, np.where(m["trees"], 2, 11)).astype(np.uint8)}

    def jrc(grid, layers):
        return {"occurrence": np.where(m["water"], 90.0, 0.0).astype(np.float32)}

    monkeypatch.setattr(catalog, "search", search)
    monkeypatch.setattr(heat, "read_mosaic", read_mosaic)
    monkeypatch.setattr(landcover, "io_lulc", io_lulc)
    monkeypatch.setattr(landcover, "jrc", jrc)
    return w


def test_summer_heat_end_to_end(world):
    stats, image, corners = heat.summer_heat(LAT, LON, today=date(2026, 10, 11))
    assert {k: stats[k] for k in ("hereC", "builtC", "waterC", "treesC", "vsBuiltC", "vsWaterC", "hotter")} == {
        "hereC": 44.0, "builtC": 42.0, "waterC": 30.0, "treesC": 35.0, "vsBuiltC": 2.0, "vsWaterC": 14.0, "hotter": True}
    assert stats["scenes"] == [{"date": "2026-04-25", "platform": "landsat-8"}, {"date": "2025-04-22", "platform": "landsat-8"},
                               {"date": "2024-04-20", "platform": "landsat-8"}]
    assert stats["years"] == [2024, 2025, 2026] and stats["window"] == ["03-15", "05-31"]
    assert (stats["radiusM"], stats["contextM"], stats["resM"]) == (300, 3000, 30)
    assert stats["scale"] == [25, 50] and stats["overpass"] == "10:30-11:00" and "error" not in stats
    assert list(stats)[:7] == ["hereC", "builtC", "waterC", "treesC", "vsBuiltC", "vsWaterC", "hotter"]
    json.dumps(stats)
    assert Image.open(io.BytesIO(image)).size == (480, 480)
    assert len(corners) == 4
    (w_lon, n_lat), (e_lon, _), (_, s_lat), _ = corners
    assert w_lon < LON < e_lon and s_lat < LAT < n_lat


def test_cloudy_passes_are_not_read_further_and_unreadable_ones_are_skipped(world):
    world["days"] += ["2025-05-01", "2026-04-01"]
    world["cloudy"].add("2025-05-01")
    world["unreadable"].add("2026-04-01")
    stats, image, _ = heat.summer_heat(LAT, LON, today=date(2026, 10, 11))
    assert len(stats["scenes"]) == 3 and stats["hereC"] == 44.0 and image
    assert ("2025-05-01", "qa_pixel.tif") in world["reads"] and ("2025-05-01", "lwir11.tif") not in world["reads"]


def test_no_clear_summer_passes_is_an_answer_not_an_error(world):
    world["days"] = []
    stats, image, corners = heat.summer_heat(LAT, LON, today=date(2026, 10, 11))
    assert image is None and corners is None
    assert stats["hereC"] is None and stats["scenes"] == [] and "2024-2026" in stats["error"]

    world["days"] = ["2024-04-20", "2025-04-22"]
    world["cloudy"].add("2025-04-22")
    stats, image, _ = heat.summer_heat(LAT, LON, today=date(2026, 10, 11))
    assert image is None and stats["scenes"] == [{"date": "2024-04-20", "platform": "landsat-8"}]
    assert "Only 1 of the 2" in stats["error"]
    json.dumps(stats)


def test_catalogue_trouble_is_explained(world, monkeypatch):
    fake = catalog.search

    def search_without_2026(api, collection, bbox, dt=None, query=None, **kw):
        if dt.startswith("2026"):
            raise RuntimeError("catalogue request failed: 503")
        return fake(api, collection, bbox, dt, query)

    world["days"] = ["2026-04-20", "2026-04-28"]
    monkeypatch.setattr(catalog, "search", search_without_2026)
    stats, image, _ = heat.summer_heat(LAT, LON, today=date(2026, 10, 11))
    assert image is None and stats["error"].endswith("(the catalogue did not answer for 2026).")

    monkeypatch.setattr(catalog, "search", lambda *a, **kw: (_ for _ in ()).throw(OSError("network unreachable")))
    stats, image, _ = heat.summer_heat(LAT, LON, today=date(2026, 10, 11))
    assert image is None and "did not answer; please try again later" in stats["error"]


def test_without_land_cover_here_is_still_measured(world):
    world["land_fails"] = True
    stats, image, _ = heat.summer_heat(LAT, LON, today=date(2026, 10, 11))
    assert stats["hereC"] == 44.0 and stats["builtC"] is None and stats["hotter"] is None and image


def test_programming_errors_raise(world, monkeypatch):
    monkeypatch.setattr(heat, "read_mosaic", lambda hrefs, grid, **kw: None)     # a reader returning nonsense
    with pytest.raises(TypeError):
        heat.summer_heat(LAT, LON, today=date(2026, 10, 11))
    with pytest.raises(ValueError):
        heat.summer_heat(95.0, LON)
