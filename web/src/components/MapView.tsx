import maplibregl, { type Map as MLMap, type StyleSpecification } from "maplibre-gl";
import { useEffect, useRef } from "react";
import { config } from "../lib/config";
import { useThemeValue } from "../lib/theme";
import type { Corners } from "../lib/types";

export type ImageOverlay = { url: string; corners: Corners; opacity?: number; dim?: boolean } | null;
/** A dot drawn above every other layer (people's standing-water reports). `color` must be a CSS colour MapLibre can
 *  parse (no CSS variables). */
export type MapPoint = { id: string; lon: number; lat: number; color: string; selected?: boolean };

type Props = {
  className?: string;
  center?: [number, number];
  zoom?: number;
  bbox?: number[];
  satellite?: boolean;
  memory?: ImageOverlay;          // historic water layer (blue / amber / red)
  frame?: ImageOverlay;           // time-machine satellite frame
  radar?: ImageOverlay;           // radar-seen flood water
  lakesUrl?: string | null;       // GeoJSON of water bodies with grade properties
  highlightLake?: string | null;
  marker?: [number, number] | null;
  points?: MapPoint[] | null;     // dots on top of everything; a selected one is drawn larger
  onPointClick?: (id: string) => void;
  interactive?: boolean;
  scrollZoom?: boolean;
  revealMs?: number;              // fade the memory layer in once (the landing page's one orchestrated moment)
  onLakeClick?: (props: Record<string, any>) => void;
  onMapClick?: (lngLat: [number, number]) => void;
  onReady?: (map: MLMap) => void;
  attribution?: string;
};

const GRADE_FILL: any = ["match", ["get", "grade"], "A", "#1F4F99", "B", "#3D7FC4", "C", "#D9901A", "D", "#E0662C", "E", "#D23A35", "#7C8A9C"];
const SELECTED: any = ["boolean", ["get", "selected"], false];
const POINT_HIT_PX = 10;          // a finger-sized target around the 7 px dots

function pointsData(points: MapPoint[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: points.map((p) => ({
      type: "Feature", properties: { id: p.id, color: p.color, selected: !!p.selected },
      geometry: { type: "Point", coordinates: [p.lon, p.lat] },
    })),
  };
}

function setPoints(map: MLMap, points: MapPoint[] | null | undefined, key: { current: string }) {
  if (!points) {
    ["points-circle", "points-halo"].forEach((l) => map.getLayer(l) && map.removeLayer(l));
    if (map.getSource("points")) map.removeSource("points");
    key.current = "";
    return;
  }
  const k = JSON.stringify(points);
  const src = map.getSource("points") as maplibregl.GeoJSONSource | undefined;
  if (!src) {
    map.addSource("points", { type: "geojson", data: pointsData(points) });
    // a soft ring under the selected dot, so its white edge still reads on the pale basemap
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    map.addLayer({
      id: "points-halo", type: "circle", source: "points", filter: SELECTED,
      paint: { "circle-color": dark ? "#ffffff" : "#13233a", "circle-opacity": dark ? 0.3 : 0.22, "circle-radius": 16, "circle-blur": 0.35 },
    });
    map.addLayer({
      id: "points-circle", type: "circle", source: "points",
      layout: { "circle-sort-key": ["case", SELECTED, 1, 0] },
      paint: {
        "circle-color": ["get", "color"],
        "circle-radius": ["case", SELECTED, 10, 7],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": ["case", SELECTED, 3, 2],
      },
    });
  } else if (k !== key.current) {
    src.setData(pointsData(points));
  }
  key.current = k;
  const order = map.getLayersOrder();
  if (order[order.length - 1] !== "points-circle" || order[order.length - 2] !== "points-halo") {
    map.moveLayer("points-halo");                    // stay above lakes and images
    map.moveLayer("points-circle");
  }
}

function basemap(dark: boolean, satellite: boolean): string | StyleSpecification {
  const cfg = config();
  if (cfg.mapKey) {
    const style = satellite ? "Hybrid" : "Monochrome";
    return `https://maps.geo.${cfg.mapRegion ?? cfg.region}.amazonaws.com/v2/styles/${style}/descriptor?key=${cfg.mapKey}&color-scheme=${dark ? "Dark" : "Light"}`;
  }
  if (satellite) {
    return {
      version: 8,
      glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
      sources: {
        esri: {
          type: "raster", tileSize: 256, maxzoom: 18,
          tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
          attribution: "Imagery: Esri, Maxar, Earthstar Geographics",
        },
      },
      layers: [{ id: "esri", type: "raster", source: "esri" }],
    };
  }
  return `https://tiles.openfreemap.org/styles/${dark ? "dark" : "positron"}`;
}

function setImage(map: MLMap, id: string, ov: ImageOverlay, before?: string, revealMs?: number) {
  const layerId = `${id}-layer`;
  if (!ov) {
    if (map.getLayer(layerId)) map.removeLayer(layerId);
    if (map.getSource(id)) map.removeSource(id);
    return;
  }
  const coords = ov.corners as unknown as [[number, number], [number, number], [number, number], [number, number]];
  const src = map.getSource(id) as maplibregl.ImageSource | undefined;
  if (src) {
    if ((src as any).url !== ov.url) src.updateImage({ url: ov.url, coordinates: coords });
  } else {
    map.addSource(id, { type: "image", url: ov.url, coordinates: coords });
  }
  // a dimmed image lets the water-memory colours above it carry the picture: washed out like a print on
  // survey paper in the light theme, darkened in the dark theme
  const dark = document.documentElement.getAttribute("data-theme") === "dark";
  const sat = ov.dim ? (dark ? -0.7 : -0.85) : 0;
  const bmax = ov.dim && dark ? 0.55 : 1;
  const bmin = ov.dim && !dark ? 0.42 : 0;
  if (!map.getLayer(layerId)) {
    map.addLayer({ id: layerId, type: "raster", source: id, paint: { "raster-opacity": revealMs ? 0 : ov.opacity ?? 1, "raster-fade-duration": 250,
      "raster-resampling": "linear", "raster-saturation": sat, "raster-brightness-max": bmax, "raster-brightness-min": bmin } },
      before && map.getLayer(before) ? before : undefined);
    if (revealMs) {
      map.setPaintProperty(layerId, "raster-opacity-transition", { duration: revealMs, delay: 300 });
      requestAnimationFrame(() => map.getLayer(layerId) && map.setPaintProperty(layerId, "raster-opacity", ov.opacity ?? 1));
    }
  } else {
    map.setPaintProperty(layerId, "raster-opacity", ov.opacity ?? 1);
    if (map.getPaintProperty(layerId, "raster-saturation") !== sat) map.setPaintProperty(layerId, "raster-saturation", sat);
    if (map.getPaintProperty(layerId, "raster-brightness-max") !== bmax) map.setPaintProperty(layerId, "raster-brightness-max", bmax);
    if (map.getPaintProperty(layerId, "raster-brightness-min") !== bmin) map.setPaintProperty(layerId, "raster-brightness-min", bmin);
  }
}

export default function MapView(p: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const props = useRef(p);
  props.current = p;
  const theme = useThemeValue();
  const hoverId = useRef<string | null>(null);
  const pointsKey = useRef("");
  const deferred = useRef(false);

  function sync() {
    const map = mapRef.current;
    if (!map) return;
    if (!map.isStyleLoaded()) {
      // tiles or a new basemap are still loading: apply the latest props once the map settles, rather than only
      // on the next render (data that arrives once, like the points, would otherwise wait for an unrelated render)
      if (!deferred.current) {
        deferred.current = true;
        map.once("idle", () => { deferred.current = false; sync(); });
      }
      return;
    }
    const q = props.current;
    if (q.lakesUrl) {
      if (!map.getSource("lakes")) {
        map.addSource("lakes", { type: "geojson", data: q.lakesUrl, promoteId: "lakeId" });
        map.addLayer({ id: "lakes-fill", type: "fill", source: "lakes", filter: ["==", ["get", "kind"], "lake"],
          paint: { "fill-color": GRADE_FILL, "fill-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 0.55, 0.28] } });
        map.addLayer({ id: "lakes-line", type: "line", source: "lakes",
          paint: { "line-color": GRADE_FILL, "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.6, 14, 2.2] } });
        map.addLayer({ id: "lakes-focus", type: "line", source: "lakes", filter: ["==", ["get", "lakeId"], ""],
          paint: { "line-color": "#FFD60A", "line-width": 3 } });
      }
      map.setFilter("lakes-focus", ["==", ["get", "lakeId"], q.highlightLake ?? ""]);
    } else if (map.getSource("lakes")) {
      ["lakes-focus", "lakes-line", "lakes-fill"].forEach((l) => map.getLayer(l) && map.removeLayer(l));
      map.removeSource("lakes");
    }
    const firstLake = map.getLayer("lakes-fill") ? "lakes-fill" : undefined;
    setImage(map, "frame", q.frame ?? null, firstLake);
    setImage(map, "memory", q.memory ?? null, firstLake, q.revealMs);
    setImage(map, "radar", q.radar ?? null, firstLake);
    setPoints(map, q.points, pointsKey);
  }

  useEffect(() => {
    if (!el.current) return;
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    const map = new maplibregl.Map({
      container: el.current,
      style: basemap(dark, !!p.satellite),
      center: p.center ?? [78.5, 20.5],
      zoom: p.zoom ?? 4,
      attributionControl: { compact: true, customAttribution: p.attribution ?? "Water: JRC Global Surface Water, USGS Landsat, Copernicus Sentinel" },
      interactive: p.interactive !== false,
      scrollZoom: p.scrollZoom !== false,
      cooperativeGestures: false,
      dragRotate: false,
      pitchWithRotate: false,
    });
    mapRef.current = map;
    deferred.current = false;     // a new map (React may mount twice in development): nothing is waiting on it yet
    pointsKey.current = "";
    if (p.interactive !== false) map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("style.load", sync);
    map.on("load", () => {
      // MapLibre opens the compact attribution at first; start it folded so it does not cover the map on phones
      el.current?.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
      sync();
      if (props.current.bbox) map.fitBounds(props.current.bbox as any, { padding: 30, duration: 0 });
      props.current.onReady?.(map);
    });
    // the point nearest the pointer within a finger-sized box, so small dots are easy to hit on phones
    const pointAt = (at: maplibregl.Point): string | null => {
      if (!map.getLayer("points-circle")) return null;
      const r = POINT_HIT_PX;
      const hits = map.queryRenderedFeatures([[at.x - r, at.y - r], [at.x + r, at.y + r]], { layers: ["points-circle"] });
      let best: string | null = null;
      let bestD = Infinity;
      for (const f of hits) {
        const s = map.project((f.geometry as GeoJSON.Point).coordinates as [number, number]);
        const d = (s.x - at.x) ** 2 + (s.y - at.y) ** 2;
        if (d < bestD) { bestD = d; best = String(f.properties?.id ?? ""); }
      }
      return best || null;
    };
    let overPoint = false;
    map.on("mousemove", (e) => {   // registered before the lake handlers, so a lake under the pointer keeps its cursor
      if (pointAt(e.point)) { map.getCanvas().style.cursor = "pointer"; overPoint = true; }
      else if (overPoint) { map.getCanvas().style.cursor = ""; overPoint = false; }
    });
    map.on("mousemove", "lakes-fill", (e) => {
      map.getCanvas().style.cursor = "pointer";
      const id = e.features?.[0]?.id as string | undefined;
      if (hoverId.current && hoverId.current !== id) map.setFeatureState({ source: "lakes", id: hoverId.current }, { hover: false });
      if (id) { map.setFeatureState({ source: "lakes", id }, { hover: true }); hoverId.current = id; }
    });
    map.on("mouseleave", "lakes-fill", () => {
      map.getCanvas().style.cursor = "";
      if (hoverId.current) map.setFeatureState({ source: "lakes", id: hoverId.current }, { hover: false });
      hoverId.current = null;
    });
    map.on("click", (e) => {
      const point = props.current.onPointClick ? pointAt(e.point) : null;
      if (point) { props.current.onPointClick!(point); return; }
      const hit = map.getLayer("lakes-fill") ? map.queryRenderedFeatures(e.point, { layers: ["lakes-fill"] }) : [];
      if (hit.length && props.current.onLakeClick) props.current.onLakeClick(hit[0].properties as any);
      else props.current.onMapClick?.([e.lngLat.lng, e.lngLat.lat]);
    });
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(el.current);
    return () => { ro.disconnect(); map.remove(); mapRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // basemap follows the theme and the satellite switch
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.setStyle(basemap(theme === "dark", !!p.satellite), { diff: false });
  }, [theme, p.satellite]);

  useEffect(() => { sync(); }); // overlays follow props on every render (cheap: only changed sources update)

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !p.bbox) return;
    if (map.loaded()) map.fitBounds(p.bbox as any, { padding: 30, duration: 600 });
  }, [p.bbox?.join(",")]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markerRef.current?.remove();
    markerRef.current = null;
    if (p.marker) {
      const dot = document.createElement("div");
      dot.className = "h-5 w-5 rounded-full border-[3px] border-white bg-built shadow-[0_0_0_2px_rgb(var(--built))]";
      markerRef.current = new maplibregl.Marker({ element: dot }).setLngLat(p.marker).addTo(map);
    }
  }, [p.marker?.join(",")]);

  return <div ref={el} className={p.className ?? "h-full w-full"} />;
}
