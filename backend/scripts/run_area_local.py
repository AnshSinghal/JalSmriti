"""Run the whole area pipeline on this computer (real satellite data, mocked AWS) and keep the results.

    python backend/scripts/run_area_local.py bengaluru [--steps prepare,scenes,static,latest,radar,names,aggregate]

Outputs go to .local/ (site/ = what CloudFront would serve, data/ = the private bucket, table-<area>.json =
DynamoDB items). The local stack (scripts/local_stack.py) serves these to the website.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from localenv import LOCAL, create_table, dump_table, load_table, setup_env  # noqa: E402

setup_env()

from moto import mock_aws  # noqa: E402

ALL = ["prepare", "scenes", "static", "latest", "radar", "names", "aggregate"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("area")
    ap.add_argument("--steps", default=",".join(ALL))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit-scenes", type=int, default=0)
    args = ap.parse_args()
    steps = args.steps.split(",")
    snap = LOCAL / f"table-{args.area}.json"
    with mock_aws():
        create_table()
        load_table(snap)
        import area as H
        t0 = time.time()
        if "prepare" in steps:
            r = H.prepare({"areaId": args.area})
            print("prepare", r, f"{time.time() - t0:.0f}s", flush=True)
        if "scenes" in steps:
            from jalsmriti import storage
            jobs = storage.get_data_json(f"areas/{args.area}/scenes.json")
            done = {k.rsplit("/", 1)[-1] for k in storage.list_keys("data", f"areas/{args.area}/looks/")}
            todo = [j for j in jobs if f"{j['season']}-{j['source']}-{j['date']}.json" not in done or j.get("frame")
                    and not storage.data_exists(f"areas/{args.area}/frames/{j['season']}.json")]
            if args.limit_scenes:
                todo = todo[:args.limit_scenes]
            print(f"scenes: {len(todo)} to do of {len(jobs)}", flush=True)
            with ThreadPoolExecutor(args.workers) as ex:
                futs = {ex.submit(H.process_scene, j): j for j in todo}
                for i, f in enumerate(as_completed(futs), 1):
                    j = futs[f]
                    try:
                        f.result()
                        print(f"  [{i}/{len(todo)}] {j['season']} {j['source']} {j['date']}{' +frame' if j['frame'] else ''}"
                              f"  {time.time() - t0:.0f}s", flush=True)
                    except Exception as e:
                        print(f"  [{i}/{len(todo)}] FAILED {j['season']} {j['itemId']}: {e}", flush=True)
        for name, fn in (("static", H.static_layers), ("latest", H.latest_quality), ("radar", H.radar_events),
                         ("names", H.name_lakes), ("aggregate", H.aggregate)):
            if name in steps:
                t1 = time.time()
                try:
                    r = fn({"areaId": args.area, "budgetSeconds": 900})
                    print(name, json.dumps(r)[:300], f"{time.time() - t1:.0f}s", flush=True)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(name, "FAILED", e, flush=True)
        n = dump_table(snap)
        print(f"saved {n} items to {snap}  total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
