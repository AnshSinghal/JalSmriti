"""Weekly lake watch (EventBridge Scheduler -> Step Functions Map -> this check -> Amazon SNS email).

For every lake somebody watches, the newest clear Sentinel-2 look is compared with the last one checked:
  * new bare ground or construction inside the historic outline (possible earth filling / dumping),
  * floating weeds covering most of the water,
  * the water spread halving between two post-monsoon looks.
Subscribers get one email per alert (an SNS filter policy on lake_id routes it only to them).
"""
from __future__ import annotations

import datetime as dt
import json
import logging

import numpy as np

from jalsmriti import catalog, landcover, storage, store, water
from jalsmriti import config as C
from jalsmriti.raster import Grid, from_lonlat_geom, rasterize_labels, utm_crs, zonal_count

log = logging.getLogger()
log.setLevel(logging.INFO)

NEW_BARE_HA = 0.4
WEED_ALERT_PCT = 60.0


def sweep(event, context=None):
    items = store.query_all("WATCHED")
    return {"lakes": [{"lakeId": it["SK"]} for it in items if int(it.get("count", 0)) > 0][:500]}


def check(event, context=None):
    lake_id = event["lakeId"]
    lake = store.get(f"LAKE#{lake_id}")
    if not lake:
        return {"ok": False, "why": "no lake"}
    state = store.get("WATCHED", lake_id) or {}
    from shapely.geometry import shape
    geom_ll = shape(lake["geometry"])
    crs = utm_crs(lake["lon"], lake["lat"])
    geom = from_lonlat_geom(geom_ll, crs)
    minx, miny, maxx, maxy = geom.bounds
    bbox = list(geom_ll.buffer(0.004).bounds)
    g = Grid.for_bbox(bbox, 20.0, crs=crs)
    labels = rasterize_labels([geom], g)
    since = state.get("lastDate") or (dt.date.today() - dt.timedelta(days=40)).isoformat()
    items = catalog.search(C.EARTH_SEARCH, C.S2_COLLECTION, bbox, f"{since}/{dt.date.today().isoformat()}",
                           {"eo:cloud_cover": {"lt": 50}}, limit=50)
    items = [it for it in items if catalog.item_date(it).isoformat() > since]
    items.sort(key=catalog.item_date, reverse=True)
    for it in items[:5]:
        passes = catalog.same_pass_items("S2", bbox, it)
        det = water.detect("S2", passes, g, bands=("red", "swir22", "blue"))
        tot = int(zonal_count(labels, 1)[0])
        clr = int(zonal_count(labels, 1, det["clear"])[0])
        if tot == 0 or clr < 0.85 * tot:
            continue
        r = det["refl"]
        with np.errstate(invalid="ignore", divide="ignore"):
            ndvi = (r["nir"] - r["red"]) / (r["nir"] + r["red"])
            bsi = ((r["swir16"] + r["red"]) - (r["nir"] + r["blue"])) / ((r["swir16"] + r["red"]) + (r["nir"] + r["blue"]))
        occ = landcover.jrc(g, layers=("occurrence",))["occurrence"]
        typical = occ >= 50
        bare = det["clear"] & ~det["water"] & (bsi > 0.05) & (ndvi < 0.15) & (labels > 0)
        weed = det["clear"] & typical & ~det["water"] & (ndvi > C.FLOATING_VEG_NDVI) & (labels > 0)
        px_ha = g.px_area_m2 / 1e4
        now = {"date": catalog.item_date(it).isoformat(), "waterHa": round(float((det["water"] & (labels > 0)).sum()) * px_ha, 2),
               "bareHa": round(float(bare.sum()) * px_ha, 2), "weedHa": round(float(weed.sum()) * px_ha, 2)}
        alerts = []
        prev_bare = state.get("bareHa")
        if prev_bare is not None and now["bareHa"] - float(prev_bare) >= NEW_BARE_HA:
            alerts.append(f"New bare ground inside the lake's historic outline: {now['bareHa'] - float(prev_bare):.1f} ha "
                          f"more than on {state.get('lastDate')}. This can mean earth filling, dumping or construction.")
        denom = now["waterHa"] + now["weedHa"]
        if denom > 0.5 and 100 * now["weedHa"] / denom >= WEED_ALERT_PCT and (state.get("weedPct") or 0) < WEED_ALERT_PCT:
            alerts.append(f"Floating weeds now cover {round(100 * now['weedHa'] / denom)}% of the water surface.")
        prev_w = state.get("waterHa")
        month = int(now["date"][5:7])
        if prev_w and float(prev_w) > 1 and now["waterHa"] < 0.5 * float(prev_w) and month in (10, 11, 12, 1):
            alerts.append(f"The water spread fell from {float(prev_w):g} ha to {now['waterHa']:g} ha after the monsoon.")
        store.update("WATCHED", lake_id, sets={"lastDate": now["date"], "waterHa": now["waterHa"], "bareHa": now["bareHa"],
                                               "weedPct": round(100 * now["weedHa"] / denom, 1) if denom > 0.5 else None,
                                               "checkedAt": store.now_iso()})
        if alerts:
            notify(lake, now, alerts)
        return {"ok": True, "alerts": len(alerts), **now}
    store.update("WATCHED", lake_id, sets={"checkedAt": store.now_iso()})
    return {"ok": True, "alerts": 0, "why": "no new clear look"}


def notify(lake: dict, now: dict, alerts: list[str]) -> None:
    site = storage.site_url()
    link = f"{site}/lake/{lake['lakeId']}" if site else f"/lake/{lake['lakeId']}"
    body = (f"JalSmriti lake watch: {lake.get('name')}\n\nOn {now['date']} the Sentinel-2 satellite showed:\n\n- "
            + "\n- ".join(alerts) + f"\n\nSee the images and add evidence: {link}\n\nThese are automatic satellite "
            "readings at 20 m resolution; please check on the ground before acting.\n\n"
            "You receive this because you chose to watch this lake. Use the unsubscribe link below to stop.")
    store.update("WATCHED", lake["lakeId"], adds={"alertsSent": 1})
    store.audit(lake.get("areaId") or "other", None, "WatchAlert", {"lakeId": lake["lakeId"]}, extra={"alerts": alerts})
    if C.LOCAL:
        log.info("ALERT %s: %s", lake["lakeId"], alerts)
        return
    import boto3
    sns = boto3.client("sns", region_name=C.REGION)
    topic = sns.create_topic(Name=C.lake_topic_name(lake["lakeId"]))["TopicArn"]       # idempotent: returns the ARN
    sns.publish(TopicArn=topic, Subject=f"JalSmriti: change seen at {lake.get('name')}"[:99], Message=body)
