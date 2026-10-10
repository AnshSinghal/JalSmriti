"""Validate the place water-memory signals against documented flood localities (writes data/place_reference.json).

    python backend/scripts/validate_places.py

Positives: localities reported flooded (docs/validation-data/flood_localities.json).
Negatives: random built-up places (Impact Observatory 2023 'built area') in the same four cities, at least 1 km from
every positive. The reference distribution of each signal among the negatives is what the index ranks against.
"""
from __future__ import annotations

import json
import math
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from localenv import ROOT, setup_env  # noqa: E402

setup_env()
import numpy as np  # noqa: E402

from jalsmriti import landcover, metrics, placecheck  # noqa: E402
from jalsmriti.raster import Grid  # noqa: E402

CITIES = {"blr": [77.45, 12.83, 77.80, 13.15], "chn": [80.05, 12.85, 80.33, 13.25], "hyd": [78.30, 17.25, 78.65, 17.55],
          "del": [76.95, 28.38, 77.40, 28.75]}
N_NEG = 60


def negatives(pos: list[dict]) -> list[dict]:
    rng = random.Random(20261010)
    out = []
    for c, b in CITIES.items():
        g = Grid.for_bbox(b, 60.0)
        io = landcover.io_lulc(g, years=(2023,))[2023]
        built = np.argwhere(io == 7)
        picks, tries = [], 0
        while len(picks) < N_NEG and tries < 5000:
            tries += 1
            r, col = built[rng.randrange(len(built))]
            lon, lat = g.rowcol_to_lonlat(r, col)
            if any(math.hypot((lon - p["lon"]) * 111 * math.cos(math.radians(lat)), (lat - p["lat"]) * 111) < 1.0 for p in pos):
                continue
            picks.append({"city": c, "name": f"random-{c}-{len(picks)}", "lat": round(lat, 5), "lon": round(lon, 5)})
        out += picks
    return out


def auc(scores, labels):
    s, y = np.array(scores, float), np.array(labels)
    P, N = s[y == 1], s[y == 0]
    return float(np.mean([(p > n) + 0.5 * (p == n) for p in P for n in N]))


def main():
    pos = json.loads((ROOT / "docs/validation-data/flood_localities.json").read_text())["localities"]
    cache = ROOT / ".local" / "place_signals.json"
    done = json.loads(cache.read_text()) if cache.exists() else {}
    neg = negatives(pos)
    pts = [dict(p, label=1) for p in pos] + [dict(n, label=0) for n in neg]
    todo = [p for p in pts if p["name"] not in done]
    print(f"{len(pts)} points ({len(pos)} flooded, {len(neg)} random built-up), {len(todo)} to compute", flush=True)

    def run(p):
        for attempt in range(3):
            try:
                return p["name"], placecheck.signals(p["lat"], p["lon"])
            except Exception as ex:
                err = ex
                time.sleep(3)
        print("  failed", p["name"], err, flush=True)
        return p["name"], None

    t0 = time.time()
    with ThreadPoolExecutor(3) as ex:
        for i, (name, sig) in enumerate(ex.map(run, todo), 1):
            if sig:
                done[name] = sig
            if i % 10 == 0:
                cache.write_text(json.dumps(done))
                print(f"  {i}/{len(todo)}  {time.time() - t0:.0f}s", flush=True)
    cache.write_text(json.dumps(done))
    rows = [dict(p, **done[p["name"]]) for p in pts if p["name"] in done]
    negs = [r for r in rows if r["label"] == 0]
    ref = {k: sorted(float(r[k]) for r in negs if r.get(k) is not None) for k, _ in metrics.PLACE_SIGNALS}
    out_path = ROOT / "backend/src/jalsmriti/data/place_reference.json"
    out_path.write_text(json.dumps({"about": "Distribution of each water-memory signal among random built-up places in "
                                             "Bengaluru, Chennai, Hyderabad and Delhi-NCR (see docs/validation.md).",
                                    "n": len(negs), "builtUpRandom": ref}, separators=(",", ":")))
    metrics._reference.cache_clear()
    labels = [r["label"] for r in rows]
    report = {"n_flooded": sum(labels), "n_random": len(labels) - sum(labels), "signals": {}}
    for k, higher in metrics.PLACE_SIGNALS:
        sc = [(r[k] if higher else -r[k]) for r in rows]
        report["signals"][k] = round(auc(sc, labels), 3)
    idx = [metrics.water_memory_index(r)["index"] for r in rows]
    report["index_auc"] = round(auc(idx, labels), 3)
    for c in CITIES:
        sub = [(i, l) for i, l, r in zip(idx, labels, rows) if r["city"] == c]
        report[f"index_auc_{c}"] = round(auc([s for s, _ in sub], [l for _, l in sub]), 3)
    tiers = {}
    for i, r in zip(idx, rows):
        t = "strong" if i >= 70 else "some" if i >= 45 else "little"
        tiers.setdefault(t, [0, 0])[r["label"]] += 1
    report["tiers_random_vs_flooded"] = tiers
    (ROOT / "docs/validation-data/place_validation.json").write_text(json.dumps({"report": report, "rows": rows}, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
