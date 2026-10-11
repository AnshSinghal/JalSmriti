"""One Lambda for all imagery work, dispatched by task name (keeps the deployment small and warm)."""
from __future__ import annotations

import area
import lake
import place
import watch

TASKS = {
    "area.prepare": area.prepare, "area.process_scene": area.process_scene, "area.static_layers": area.static_layers,
    "area.latest_quality": area.latest_quality, "area.radar_events": area.radar_events, "area.name_lakes": area.name_lakes,
    "area.aggregate": area.aggregate, "area.failed": area.failed, "area.rename": area.rename,
    "place.static": place.static, "place.optical": place.optical, "place.radar": place.radar_step, "place.heat": place.heat_step,
    "place.score": place.score, "place.failed": place.failed,
    "lake.find": lake.find, "lake.looks": lake.looks, "lake.static": lake.static, "lake.latest": lake.latest,
    "lake.aggregate": lake.aggregate, "lake.failed": lake.failed,
    "watch.sweep": watch.sweep, "watch.check": watch.check,
}


def handler(event, context=None):
    task = event.get("task")
    if task not in TASKS:
        raise ValueError(f"unknown task {task!r}")
    return TASKS[task](event, context)
