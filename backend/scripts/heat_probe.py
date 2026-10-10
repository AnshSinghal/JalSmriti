"""Measure summer heat at a few known places with real satellite data: print the numbers, save the images.

    JALSMRITI_LOCAL=1 PYTHONPATH=backend/src python backend/scripts/heat_probe.py [name ...] [--out DIR]

For each place it prints the seconds taken and the stats JSON, and saves the map image as <name>.webp (what the site
serves) and <name>.png (to look at anywhere). Uses the network (Microsoft Planetary Computer); nothing goes to AWS.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from localenv import setup_env  # noqa: E402

setup_env()

from PIL import Image  # noqa: E402

from jalsmriti import heat  # noqa: E402

POINTS = {                                   # name: (lat, lon)
    "bellandur": (12.93520, 77.68070),       # Bengaluru: dense IT corridor east of Bellandur lake
    "velachery": (12.98150, 80.21800),       # Chennai: built-up beside Velachery lake
    "cubbon-park": (12.97630, 77.59290),     # Bengaluru: the big central park
    "gurugram-sector-56": (28.42000, 77.10700),   # Delhi-NCR: dry, almost no water
    "kathmandu-teku": (27.69500, 85.30500),  # Kathmandu (1,300 m): old town at the Bagmati-Bishnumati confluence
}
OUT = os.environ.get("HEAT_PROBE_OUT",
                     "/tmp/claude-0/-home-claude/1a6db558-2905-535a-bb81-f9b7df0ec310/scratchpad/heat")
COLUMNS = (("hereC", "here"), ("builtC", "built"), ("waterC", "water"), ("treesC", "trees"), ("vsBuiltC", "vsBuilt"),
           ("vsWaterC", "vsWater"))


def _row(name: str, secs: float, s: dict) -> str:
    cells = "".join(f"{'-' if s.get(k) is None else s[k]:>8}" for k, _ in COLUMNS)
    tail = f"  {s['error']}" if s.get("error") else ""
    return f"{name:<20}{secs:>6.1f}{cells}{len(s['scenes']):>8}  {s.get('scale')}{tail}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*", metavar="name", help=f"places to measure (default: all of {', '.join(POINTS)})")
    ap.add_argument("--out", default=OUT, help=f"folder for the images (default {OUT})")
    args = ap.parse_args()
    unknown = [n for n in args.names if n not in POINTS]
    if unknown:
        ap.error(f"unknown place(s) {', '.join(unknown)}; choose from {', '.join(POINTS)}")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in args.names or list(POINTS):
        lat, lon = POINTS[name]
        t0 = time.time()
        stats, webp, corners = heat.summer_heat(lat, lon)
        secs = time.time() - t0
        print(f"\n== {name} ({lat}, {lon})  {secs:.1f} s\n{json.dumps(stats)}", flush=True)
        if webp:
            (out / f"{name}.webp").write_bytes(webp)
            Image.open(io.BytesIO(webp)).save(out / f"{name}.png")
            print(f"image: {out / name}.webp ({len(webp) / 1024:.0f} KB) and .png; corners {json.dumps(corners)}")
        rows.append((name, secs, stats))
    print(f"\n{'place':<20}{'s':>6}{''.join(f'{label:>8}' for _, label in COLUMNS)}{'passes':>8}  scale")
    for name, secs, s in rows:
        print(_row(name, secs, s))


if __name__ == "__main__":
    main()
