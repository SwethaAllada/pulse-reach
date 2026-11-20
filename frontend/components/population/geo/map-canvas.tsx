"use client";

import { useEffect, useRef } from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Map as MlMap, StyleSpecification, GeoJSONSource } from "maplibre-gl";
import type { FacilityPointOut, MapAreaOut, Severity } from "@/lib/api/geo-types";
import { FACILITY_LAYER_META, SEVERITY_META, areaMarkersGeoJSON, facilitiesGeoJSON } from "@/lib/population/geo";

/** Basemap: OpenFreeMap vector tiles (OpenMapTiles schema; no key, OSM data). Recoloured from theme tokens. */
const TILES = "https://tiles.openfreemap.org/planet";
/** Copied from node_modules by `scripts/copy-maplibre-worker.mjs` (predev / prebuild). */
const WORKER_URL = "/vendor/maplibre-gl-worker.mjs";
const GLYPHS = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";
const ATTRIBUTION =
  '<a href="https://openfreemap.org" target="_blank" rel="noreferrer">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/" target="_blank" rel="noreferrer">OpenMapTiles</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors';
/** Abu Dhabi Emirate (covers every published facility point after geometry repair). */
const EMIRATE_BOUNDS: [[number, number], [number, number]] = [
  [51.4, 22.6],
  [56.1, 24.9],
];

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "gray";
}

function baseStyle(): StyleSpecification {
  const c = (n: string) => token(n);
  return {
    version: 8,
    glyphs: GLYPHS,
    sources: { omt: { type: "vector", url: TILES, attribution: ATTRIBUTION } },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": c("--map-land") } },
      { id: "water", type: "fill", source: "omt", "source-layer": "water", paint: { "fill-color": c("--map-water") } },
      {
        id: "roads",
        type: "line",
        source: "omt",
        "source-layer": "transportation",
        filter: ["in", ["get", "class"], ["literal", ["motorway", "trunk", "primary", "secondary", "tertiary"]]],
        paint: {
          "line-color": c("--map-road"),
          "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0.4, 10, 1.2, 14, 3],
        },
      },
      {
        id: "admin",
        type: "line",
        source: "omt",
        "source-layer": "boundary",
        filter: ["<=", ["get", "admin_level"], 4],
        paint: { "line-color": c("--map-boundary"), "line-width": 0.8, "line-dasharray": [3, 2] },
      },
      {
        id: "places",
        type: "symbol",
        source: "omt",
        "source-layer": "place",
        filter: ["in", ["get", "class"], ["literal", ["city", "town", "suburb", "village"]]],
        layout: {
          "text-field": ["coalesce", ["get", "name:en"], ["get", "name_en"], ["get", "name"]],
          "text-font": ["Noto Sans Regular"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 6, 10, 12, 13],
        },
        paint: { "text-color": c("--map-label"), "text-halo-color": c("--map-label-halo"), "text-halo-width": 1.4 },
      },
    ],
  };
}

function severityColorExpr(): unknown[] {
  const expr: unknown[] = ["match", ["get", "severity"]];
  for (const s of Object.keys(SEVERITY_META) as Severity[]) expr.push(s, token(SEVERITY_META[s].token));
  expr.push(token("--map-boundary"));
  return expr;
}

function addDataLayers(map: MlMap) {
  map.addSource("areas", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addSource("facilities", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({
    id: "facilities",
    type: "circle",
    source: "facilities",
    paint: {
      "circle-radius": [
        "interpolate",
        ["linear"],
        ["zoom"],
        7,
        ["match", ["get", "layer"], "hospitals", 2.6, 1.3],
        12,
        ["match", ["get", "layer"], "hospitals", FACILITY_LAYER_META.hospitals.radius, FACILITY_LAYER_META.clinics.radius],
      ],
      "circle-color": ["match", ["get", "layer"], "hospitals", token("--map-label"), token("--map-facility-other")],
      "circle-opacity": 0.7,
      "circle-stroke-color": token("--map-label-halo"),
      "circle-stroke-width": 0.6,
    },
  });
  const sev = severityColorExpr();
  const neutral = token("--accent-primary");
  const color = ["case", ["==", ["get", "severity"], "NONE"], neutral, sev] as never;
  const radius = [
    "interpolate",
    ["linear"],
    ["zoom"],
    6,
    ["case", ["<", ["get", "size"], 0], 6, ["+", 6, ["*", 18, ["get", "size"]]]],
    12,
    ["case", ["<", ["get", "size"], 0], 10, ["+", 10, ["*", 34, ["get", "size"]]]],
  ] as never;
  map.addLayer({
    id: "area-halo",
    type: "circle",
    source: "areas",
    paint: { "circle-radius": radius, "circle-color": color, "circle-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 0.32, 0.2] },
  });
  map.addLayer({
    id: "area-core",
    type: "circle",
    source: "areas",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 3.5, 12, 6],
      "circle-color": ["case", ["<", ["get", "size"], 0], token("--map-label-halo"), color] as never,
      "circle-stroke-color": color,
      "circle-stroke-width": 2,
    },
  });
  map.addLayer({
    id: "area-selected",
    type: "circle",
    source: "areas",
    filter: ["==", ["get", "area_id"], ""],
    paint: { "circle-radius": radius, "circle-color": "transparent", "circle-stroke-color": token("--map-selected"), "circle-stroke-width": 3 },
  });
  map.addLayer({
    id: "area-labels",
    type: "symbol",
    source: "areas",
    minzoom: 8,
    layout: {
      "text-field": ["get", "label"],
      "text-font": ["Noto Sans Regular"],
      "text-size": 12,
      "text-offset": [0, 1.6],
      "text-anchor": "top",
      "text-optional": true,
    },
    paint: { "text-color": token("--text-primary"), "text-halo-color": token("--map-label-halo"), "text-halo-width": 1.6 },
  });
  // Selected facility: a ring at its published coordinates, drawn above the area markers so a
  // deep-linked facility stays visible. Re-added here so it survives theme restyles.
  map.addLayer({
    id: "facility-selected",
    type: "circle",
    source: "facilities",
    filter: ["==", ["get", "ch_fid"], ""],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 6, 12, 10, 15, 13],
      "circle-color": "transparent",
      "circle-stroke-color": token("--map-selected"),
      "circle-stroke-width": 3,
    },
  });
}

const MAP_FALLBACK = "The base map could not be loaded. Facility and area data are still listed.";
const OFFLINE_FALLBACK = "You appear to be offline, so the base map could not be loaded. Facility and area data are still listed.";
/** Network-level failures (style, TileJSON, glyphs or tiles), not data or rendering bugs. */
const NETWORK_ERROR = /Failed to fetch|NetworkError|Load failed|AJAXError|ERR_INTERNET_DISCONNECTED|ERR_NAME_NOT_RESOLVED/i;

export interface MapCanvasProps {
  areas: MapAreaOut[];
  metric: string;
  severity: Map<string, Severity>;
  facilities: FacilityPointOut[];
  showFacilities: boolean;
  showAlerts: boolean;
  selectedId: string | null;
  /** `ch_fid` of the selected facility (ringed and flown to). */
  selectedFacilityId?: string | null;
  theme: string;
  onSelect: (areaId: string | null) => void;
  onSelectFacility?: (chFid: string) => void;
  onError: (message: string) => void;
}

/**
 * MapLibre canvas (client-only, lazy-loaded). Creates one map per mount, rebuilds the style on
 * theme change and removes the instance (and its listeners) on unmount.
 */
export default function MapCanvas(props: MapCanvasProps) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const ready = useRef(false);
  const latest = useRef(props);
  /** Whether the map has fired `load` (later tile hiccups don't replace the whole map). */
  const loaded = useRef(false);
  /** Theme the current basemap style was built for. */
  const styledFor = useRef<string | null>(null);
  useEffect(() => {
    latest.current = props;
  });

  /** Facility GeoJSON (~1,600 points) is only re-sent when the `facilities` array changes. */
  const syncFacilities = () => {
    const m = map.current;
    if (!m || !ready.current) return;
    (m.getSource("facilities") as GeoJSONSource | undefined)?.setData(facilitiesGeoJSON(latest.current.facilities) as never);
  };

  const sync = () => {
    const m = map.current;
    if (!m || !ready.current) return;
    const p = latest.current;
    (m.getSource("areas") as GeoJSONSource | undefined)?.setData(areaMarkersGeoJSON(p.areas, p.severity, p.metric) as never);
    m.setFilter("area-selected", ["==", ["get", "area_id"], p.selectedId ?? ""]);
    m.setFilter("facility-selected", ["==", ["get", "ch_fid"], p.selectedFacilityId ?? ""]);
    for (const id of ["area-halo", "area-core", "area-selected", "area-labels"]) m.setLayoutProperty(id, "visibility", p.showAlerts ? "visible" : "none");
    // A selected facility keeps the facility layer visible.
    const facilitiesVisible = p.showFacilities || Boolean(p.selectedFacilityId);
    m.setLayoutProperty("facilities", "visibility", facilitiesVisible ? "visible" : "none");
    m.setLayoutProperty("facility-selected", "visibility", p.selectedFacilityId ? "visible" : "none");
  };

  useEffect(() => {
    let cancelled = false;
    let hovered: string | number | null = null;
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      latest.current.onError(OFFLINE_FALLBACK);
      return;
    }
    import("maplibre-gl")
      .then((ml) => {
        if (cancelled || !el.current) return;
        ml.setWorkerUrl(WORKER_URL);
        const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const m = new ml.Map({
          container: el.current,
          style: baseStyle(),
          bounds: EMIRATE_BOUNDS,
          fitBoundsOptions: { padding: 24 },
          attributionControl: { compact: true },
          fadeDuration: reduce ? 0 : 300,
          cooperativeGestures: false,
        });
        map.current = m;
        m.addControl(new ml.NavigationControl({ showCompass: false }), "top-right");
        m.addControl(new ml.ScaleControl({ unit: "metric" }), "bottom-left");
        styledFor.current = latest.current.theme;
        m.on("load", () => {
          loaded.current = true;
          addDataLayers(m);
          ready.current = true;
          syncFacilities();
          sync();
          restyle();
          frame();
        });
        m.on("error", (e) => {
          const err = e.error as (Error & { status?: number; name?: string }) | undefined;
          const msg = `${err?.name ?? ""} ${err?.message ?? ""}`;
          // Only network failures before the first load (style, TileJSON, first tiles) replace the map;
          // individual tile errors afterwards leave the working map in place.
          if (loaded.current) return;
          if (NETWORK_ERROR.test(msg) || (typeof navigator !== "undefined" && navigator.onLine === false)) latest.current.onError(MAP_FALLBACK);
        });
        // One click handler: a facility under the pointer wins over the (larger) area halo.
        m.on("click", (e) => {
          if (!ready.current) return;
          const layers = ["facilities", "area-halo"].filter((id) => m.getLayer(id));
          const hits = m.queryRenderedFeatures(e.point, { layers });
          const facility = hits.find((f) => f.layer.id === "facilities");
          const fid = facility?.properties?.ch_fid as string | undefined;
          if (fid) return latest.current.onSelectFacility?.(fid);
          const id = hits.find((f) => f.layer.id === "area-halo")?.properties?.area_id as string | undefined;
          if (id) latest.current.onSelect(id);
        });
        m.on("mousemove", "area-halo", (e) => {
          const f = e.features?.[0];
          if (!f) return;
          if (hovered !== null) m.setFeatureState({ source: "areas", id: hovered }, { hover: false });
          hovered = f.id ?? null;
          if (hovered !== null) m.setFeatureState({ source: "areas", id: hovered }, { hover: true });
        });
        m.on("mouseleave", "area-halo", () => {
          if (hovered !== null) m.setFeatureState({ source: "areas", id: hovered }, { hover: false });
          hovered = null;
        });
        for (const id of ["area-halo", "area-core", "facilities"]) {
          m.on("mouseenter", id, () => (m.getCanvas().style.cursor = "pointer"));
          m.on("mouseleave", id, () => (m.getCanvas().style.cursor = ""));
        }
      })
      .catch(() => latest.current.onError("The interactive map could not start in this browser. Facility and area data are still listed."));
    return () => {
      cancelled = true;
      map.current?.remove();
      map.current = null;
      ready.current = false;
      loaded.current = false;
    };
    // One map per mount; handlers read the latest props through refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Facility points: only when the array changes (selection changes don't re-send ~1,600 points).
  useEffect(syncFacilities, [props.facilities]);
  // Area data, selection and layer visibility.
  useEffect(sync, [props.areas, props.metric, props.severity, props.showAlerts, props.showFacilities, props.selectedId, props.selectedFacilityId]);

  // Theme change: rebuild the recoloured style, then re-add the data layers. A change while the
  // map is still loading is applied by the load handler.
  function restyle() {
    const m = map.current;
    const theme = latest.current.theme;
    if (!m || !ready.current || styledFor.current === theme) return;
    styledFor.current = theme;
    ready.current = false;
    m.once("style.load", () => {
      addDataLayers(m);
      ready.current = true;
      syncFacilities();
      sync();
    });
    m.setStyle(baseStyle(), { diff: false });
  }
  useEffect(restyle, [props.theme]);

  // Fly to the selected facility's published point or the selected area's representative point;
  // otherwise frame the mapped area markers (the emirate when there are none). Also run once the
  // map has loaded.
  function frame() {
    const m = map.current;
    if (!m) return;
    const { areas, selectedId, selectedFacilityId, facilities } = latest.current;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (selectedFacilityId) {
      const f = facilities.find((p) => p.ch_fid === selectedFacilityId);
      if (f) m.flyTo({ center: [f.longitude, f.latitude], zoom: Math.max(m.getZoom(), 13), duration: reduce ? 0 : 800 });
      // Not (yet) among the loaded points: leave the view; the panel explains.
      return;
    }
    const pt = areas.find((a) => a.area.area_id === selectedId)?.representative_point;
    if (pt) {
      m.flyTo({ center: [pt.longitude, pt.latitude], zoom: Math.max(m.getZoom(), 11), duration: reduce ? 0 : 800 });
      return;
    }
    const pts = areas.flatMap((a) => (a.representative_point ? [a.representative_point] : []));
    const bounds: [[number, number], [number, number]] = pts.length
      ? [
          [Math.min(...pts.map((p) => p.longitude)), Math.min(...pts.map((p) => p.latitude))],
          [Math.max(...pts.map((p) => p.longitude)), Math.max(...pts.map((p) => p.latitude))],
        ]
      : EMIRATE_BOUNDS;
    m.fitBounds(bounds, { padding: 80, maxZoom: 11.5, duration: reduce ? 0 : 700 });
  }
  // `facilities` only matters for a facility deep link that arrives before the points do.
  const frameFacilities = props.selectedFacilityId ? props.facilities : null;
  useEffect(frame, [props.selectedId, props.areas, props.selectedFacilityId, frameFacilities]);

  // The canvas and MapLibre controls are never mirrored in RTL.
  return (
    <div
      ref={el}
      dir="ltr"
      role="region"
      aria-label="Map of Abu Dhabi Emirate with care facilities and approximate area markers"
      className="h-full w-full"
    />
  );
}
