"use client";

import { useEffect, useRef } from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Map as MlMap, StyleSpecification, GeoJSONSource, Popup } from "maplibre-gl";
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
}

export interface MapCanvasProps {
  areas: MapAreaOut[];
  metric: string;
  severity: Map<string, Severity>;
  facilities: FacilityPointOut[];
  showFacilities: boolean;
  showAlerts: boolean;
  selectedId: string | null;
  theme: string;
  onSelect: (areaId: string | null) => void;
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
  const popup = useRef<Popup | null>(null);
  /** Theme the current basemap style was built for. */
  const styledFor = useRef<string | null>(null);
  useEffect(() => {
    latest.current = props;
  });

  const sync = () => {
    const m = map.current;
    if (!m || !ready.current) return;
    const p = latest.current;
    (m.getSource("areas") as GeoJSONSource | undefined)?.setData(areaMarkersGeoJSON(p.areas, p.severity, p.metric) as never);
    (m.getSource("facilities") as GeoJSONSource | undefined)?.setData(facilitiesGeoJSON(p.facilities) as never);
    m.setFilter("area-selected", ["==", ["get", "area_id"], p.selectedId ?? ""]);
    for (const id of ["area-halo", "area-core", "area-selected", "area-labels"]) m.setLayoutProperty(id, "visibility", p.showAlerts ? "visible" : "none");
    m.setLayoutProperty("facilities", "visibility", p.showFacilities ? "visible" : "none");
  };

  useEffect(() => {
    let cancelled = false;
    let hovered: string | number | null = null;
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
          addDataLayers(m);
          ready.current = true;
          sync();
          restyle();
          frame();
        });
        m.on("error", (e) => {
          const msg = String(e.error?.message ?? "");
          if (/Failed to fetch|NetworkError|tiles|style/i.test(msg)) latest.current.onError("The base map could not be loaded. Facility and area data are still listed.");
        });
        m.on("click", "area-halo", (e) => {
          const id = e.features?.[0]?.properties?.area_id as string | undefined;
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
        m.on("click", "facilities", (e) => {
          const f = e.features?.[0];
          if (!f) return;
          const p = f.properties as Record<string, string | boolean>;
          const body = document.createElement("div");
          body.className = "text-xs";
          const title = document.createElement("p");
          title.className = "font-semibold text-foreground";
          title.textContent = String(p.name);
          const meta = document.createElement("p");
          meta.className = "mt-0.5 text-muted";
          meta.textContent = [FACILITY_LAYER_META[String(p.layer)]?.label ?? p.type, p.city, p.is_public === "unknown" ? null : p.is_public, p.license]
            .filter(Boolean)
            .join(" · ");
          body.append(title, meta);
          if (p.repaired) {
            const note = document.createElement("p");
            note.className = "mt-1 text-faint";
            note.textContent = "Published coordinates were transposed and have been repaired.";
            body.append(note);
          }
          popup.current?.remove();
          popup.current = new ml.Popup({ closeButton: true, maxWidth: "260px", className: "pr-popup" })
            .setLngLat((f.geometry as unknown as { coordinates: [number, number] }).coordinates)
            .setDOMContent(body)
            .addTo(m);
        });
      })
      .catch(() => latest.current.onError("The interactive map could not start in this browser. Facility and area data are still listed."));
    return () => {
      cancelled = true;
      popup.current?.remove();
      map.current?.remove();
      map.current = null;
      ready.current = false;
    };
    // One map per mount; handlers read the latest props through refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Data / layer visibility changes.
  useEffect(sync, [props.areas, props.metric, props.severity, props.facilities, props.showAlerts, props.showFacilities, props.selectedId]);

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
      sync();
    });
    m.setStyle(baseStyle(), { diff: false });
  }
  useEffect(restyle, [props.theme]);

  // Fly to the selected area's representative point; otherwise frame the mapped area markers
  // (the emirate when there are none). Also run once the map has loaded.
  function frame() {
    const m = map.current;
    if (!m) return;
    const { areas, selectedId } = latest.current;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
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
  useEffect(frame, [props.selectedId, props.areas]);

  return <div ref={el} role="region" aria-label="Map of Abu Dhabi Emirate with care facilities and approximate area markers" className="h-full w-full" />;
}
