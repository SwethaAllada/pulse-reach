"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, Building2, ExternalLink, Info, Layers, MapPinned, RotateCcw, Siren, X } from "lucide-react";
import { ApiError, api } from "@/lib/api/client";
import { cached } from "@/lib/api/cache";
import { useResource, type Resource } from "@/lib/api/resource";
import type { ConditionCode, FacilityDetailOut, FacilityRegisterSummary, MapAreaOut, MapMetric } from "@/lib/api/geo-types";
import { useAuth } from "@/lib/auth/auth-context";
import { useTheme } from "@/components/theme/use-theme";
import {
  FACILITY_LAYER_META,
  SEVERITY_META,
  SEVERITY_ORDER,
  coordinateText,
  facilityCountText,
  geoQualityLabel,
  maxSeverityByArea,
  metricText,
  periodLabel,
  publishedServiceFlags,
  sectorLabel,
  suppressedLabels,
} from "@/lib/population/geo";
import { regionLabel } from "@/lib/population/filters";
import { Segmented } from "@/components/ui/segmented";
import { buttonClass } from "@/components/ui/button-styles";
import { ResourceView } from "@/components/programmes/resource-state";
import { cn } from "@/lib/cn";

const MapCanvas = dynamic(() => import("./map-canvas"), {
  ssr: false,
  loading: () => <div aria-busy="true" aria-label="Loading map" className="skeleton h-full w-full" />,
});

const METRICS: { value: MapMetric; label: string; disease?: boolean }[] = [
  { value: "population", label: "Registered population" },
  { value: "open_care_gaps", label: "Open care gaps" },
  { value: "preventive_coverage", label: "Preventive coverage" },
  { value: "care_facilities", label: "Care facilities" },
  { value: "new_cases", label: "New diagnoses (90 days)", disease: true },
  { value: "prevalence", label: "Prevalence", disease: true },
];
const CONDITIONS: { value: ConditionCode; label: string }[] = [
  { value: "diabetes_type_2", label: "Type 2 diabetes" },
  { value: "hypertension", label: "Hypertension" },
  { value: "dyslipidaemia", label: "Dyslipidaemia" },
  { value: "asthma", label: "Asthma" },
];

const NOT_PUBLISHED =
  "Published licence record — opening hours, contact details, appointment availability and referral acceptance are not published and are not shown.";

/** Area context from the map response (applies to every area in it). */
interface AreaContext {
  period: string | null;
  asOf: string;
  minCellSize: number | null;
}

/**
 * Geographic overview for roles with `population.read`. The map shows verified facility points
 * and one approximate marker per mapped area (there are no area boundaries). The ranked area list
 * beside it is the complete, non-map equivalent. `?area=` selects an area, `?facility=` a facility
 * (mutually exclusive).
 */
export function PopulationMap() {
  const { can } = useAuth();
  const { theme } = useTheme();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const selectedId = params.get("area");
  const facilityId = params.get("facility");
  const [geography, setGeography] = useState<"district" | "local_area">("local_area");
  const [metric, setMetric] = useState<MapMetric>("open_care_gaps");
  const [condition, setCondition] = useState<ConditionCode>("diabetes_type_2");
  const [showFacilities, setShowFacilities] = useState(true);
  const [showAlerts, setShowAlerts] = useState(true);
  const [mapError, setMapError] = useState<string | null>(null);
  const [canvasKey, setCanvasKey] = useState(0);
  const disease = METRICS.find((m) => m.value === metric)?.disease;

  const allowed = can("population.read");
  const canFacilities = can("facilities.read");
  const mapKey = `${geography}|${metric}|${disease ? condition : ""}`;
  const areas = useResource(allowed ? `geo-map|${mapKey}` : null, "population.read", (s) =>
    api.populationMap({ geography, metric, condition: disease ? condition : undefined }, s), 0);
  const alerts = useResource(can("population.alerts.read") ? "geo-alerts" : null, "population.alerts.read", (s) => api.populationAlerts(s), 0);
  const facilities = useResource(canFacilities ? "geo-facilities" : null, "facilities.read", () =>
    cached("facility-points", () => api.facilityPoints()), 0);
  const facility = useResource<FacilityDetailOut | null>(
    facilityId && canFacilities ? `facility|${facilityId}` : null,
    "facilities.read",
    (s) =>
      api.facilityDetail(facilityId!, s).catch((err) => {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }),
    0
  );

  const severity = useMemo(() => maxSeverityByArea(alerts.status === "ready" ? alerts.data.items : []), [alerts]);
  const items = useMemo(() => (areas.status === "ready" ? areas.data.items : []), [areas]);
  const points = useMemo(() => (facilities.status === "ready" ? facilities.data.items : []), [facilities]);
  const selected = items.find((a) => a.area.area_id === selectedId) ?? null;
  const facilityMissing = Boolean(facilityId) && facilities.status === "ready" && !points.some((p) => p.ch_fid === facilityId);

  /** Replace the URL; an area and a facility are never selected together. */
  const update = (patch: { area?: string | null; facility?: string | null }) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };
  const select = (id: string | null) => update(id ? { area: id, facility: null } : { area: null });
  const selectFacility = (id: string | null) => update(id ? { facility: id, area: null } : { facility: null });
  const retryMap = () => {
    setMapError(null);
    setCanvasKey((k) => k + 1);
  };

  if (!allowed) return null;
  const located = items.filter((a) => a.representative_point).length;
  const unmapped = items.filter((a) => !a.representative_point);
  const alerting = items.filter((a) => severity.has(a.area.area_id)).length;
  const metricLabel = METRICS.find((m) => m.value === metric)?.label ?? metric;
  const conditionLabel = disease ? CONDITIONS.find((c) => c.value === condition)?.label : null;
  const context: AreaContext | null =
    areas.status === "ready"
      ? { period: periodLabel(areas.data.period), asOf: areas.data.as_of, minCellSize: areas.data.privacy?.min_cell_size ?? null }
      : null;

  return (
    <section aria-labelledby="geo-heading" className="reveal rounded-xl border border-border bg-surface-raised">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
        <div className="min-w-0">
          <h2 id="geo-heading" className="flex items-center gap-2 text-[15px] font-semibold text-foreground">
            <MapPinned size={16} aria-hidden="true" className="text-accent" /> Geographic overview
          </h2>
          <p className="mt-1 max-w-2xl text-[13px] text-muted">
            One marker per local area, sized by the selected measure and coloured by its highest active alert. Select a marker or
            an area to see its statistics, or a facility dot to see its published licence record.
          </p>
        </div>
        <div className="flex w-full min-w-0 flex-wrap items-center gap-2 sm:w-auto">
          <Segmented
            label="Geography level"
            value={geography}
            onChange={(g) => (setGeography(g), select(null))}
            options={[
              { value: "local_area", label: "Local areas" },
              { value: "district", label: "Districts" },
            ]}
          />
          <select aria-label="Area metric" className="h-8 min-w-0 max-w-full rounded-lg border border-border-strong bg-surface-raised px-2.5 text-sm text-foreground" value={metric} onChange={(e) => setMetric(e.target.value as MapMetric)}>
            {METRICS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
          {disease && (
            <select aria-label="Condition" className="h-8 min-w-0 max-w-full rounded-lg border border-border-strong bg-surface-raised px-2.5 text-sm text-foreground" value={condition} onChange={(e) => setCondition(e.target.value as ConditionCode)}>
              {CONDITIONS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          )}
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="relative min-h-[420px] border-b border-border lg:min-h-[560px] lg:border-b-0 lg:border-e">
          {mapError ? (
            <div role="status" className="flex h-full min-h-[420px] flex-col items-center justify-center gap-3 p-6 text-center text-sm text-muted">
              <AlertTriangle size={18} aria-hidden="true" className="text-status-insufficient" />
              <span>{mapError}</span>
              <button type="button" onClick={retryMap} className={buttonClass("secondary")}>
                <RotateCcw size={14} aria-hidden="true" /> Retry map
              </button>
            </div>
          ) : (
            <div className="absolute inset-0" dir="ltr">
              <MapCanvas
                key={canvasKey}
                areas={items}
                metric={metric}
                severity={severity}
                facilities={points}
                showFacilities={showFacilities}
                showAlerts={showAlerts}
                selectedId={selectedId}
                selectedFacilityId={facilityId}
                theme={theme}
                onSelect={select}
                onSelectFacility={selectFacility}
                onError={setMapError}
              />
            </div>
          )}
          <Legend
            measure={conditionLabel ? `${metricLabel} · ${conditionLabel}` : metricLabel}
            period={context?.period ?? null}
            showFacilities={showFacilities}
            showAlerts={showAlerts}
            onFacilities={setShowFacilities}
            onAlerts={setShowAlerts}
            facilityCount={facilities.status === "ready" ? facilities.data.total : null}
            register={facilities.status === "ready" ? (facilities.data.register ?? null) : null}
            excluded={facilities.status === "ready" ? facilities.data.excluded_without_coordinates : null}
          />
        </div>

        <div className="flex max-h-[560px] min-h-0 flex-col">
          {facilityId ? (
            <FacilityPanel
              resource={facilityMissing ? ({ status: "ready", data: null } as const) : facility}
              onClose={() => selectFacility(null)}
            />
          ) : selected && context ? (
            <AreaDetail
              area={selected}
              metric={metric}
              context={context}
              alerts={alerts.status === "ready" ? alerts.data.items.filter((a) => a.area_id === selected.area.area_id) : []}
              onClose={() => select(null)}
            />
          ) : (
            <ResourceView resource={areas} what="Area statistics">
              {(d) => (
                <>
                  <p className="border-b border-border px-5 py-2.5 text-xs text-muted">
                    {d.total} {geography === "district" ? "districts" : "local areas"} · {alerting} with active alerts · {located} mapped ·{" "}
                    as of {d.as_of}
                  </p>
                  {unmapped.length > 0 && (
                    <p className="border-b border-border px-5 py-2 text-[11px] text-faint">
                      Unmapped (no reliable facility coordinates): {unmapped.map((a) => a.area.name).join(", ")}
                    </p>
                  )}
                  <ul aria-label="Areas ranked by the selected metric" className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
                    {d.items.map((a) => (
                      <AreaRow key={a.area.area_id} area={a} metric={metric} severity={severity.get(a.area.area_id)} onSelect={() => select(a.area.area_id)} />
                    ))}
                  </ul>
                </>
              )}
            </ResourceView>
          )}
        </div>
      </div>

      <p className="flex gap-2 border-t border-border px-5 py-3 text-[11px] leading-relaxed text-faint">
        <Info size={13} aria-hidden="true" className="mt-px shrink-0" />
        <span>
          Patients have no recorded locations and areas have no official boundaries. Each area marker sits at the median of the area’s
          associated published care-facility coordinates — an approximate representative point, not the area’s centre and not where
          patients live. Areas with fewer than three such facilities are listed as unmapped. Facilities appear only at published
          coordinates. “—” means suppressed (fewer than the minimum cell size) or unavailable, never zero.
        </span>
      </p>
    </section>
  );
}

function registerTitle(r: FacilityRegisterSummary): string {
  const other = Math.max(0, r.register_total - r.in_layers);
  return [
    `${r.mappable.toLocaleString("en")} of ${r.register_total.toLocaleString("en")} published facility records are mapped.`,
    `Not shown: ${other.toLocaleString("en")} in other register layers`,
    `${r.excluded_unidentified.toLocaleString("en")} without an identifier`,
    `${r.excluded_license_status.toLocaleString("en")} by licence status (included: ${r.license_statuses_included.join(", ") || "—"})`,
    `${r.excluded_invalid_coordinates.toLocaleString("en")} with missing or invalid coordinates.`,
  ].join("; ");
}

function Legend({
  measure,
  period,
  showFacilities,
  showAlerts,
  onFacilities,
  onAlerts,
  facilityCount,
  register,
  excluded,
}: {
  measure: string;
  period: string | null;
  showFacilities: boolean;
  showAlerts: boolean;
  onFacilities: (v: boolean) => void;
  onAlerts: (v: boolean) => void;
  facilityCount: number | null;
  register: FacilityRegisterSummary | null;
  excluded: number | null;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="pointer-events-auto absolute bottom-8 start-3 z-10 max-h-[calc(100%-3rem)] w-64 max-w-[calc(100%-1.5rem)] overflow-y-auto rounded-lg border border-border bg-[color-mix(in_srgb,var(--surface-elevated)_94%,transparent)] p-3 text-xs shadow-[var(--shadow-popover)] backdrop-blur">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn("flex w-full items-center gap-1.5 text-start font-medium text-foreground lg:hidden", open && "mb-2")}
      >
        <Layers size={12} aria-hidden="true" /> {open ? "Hide legend" : "Show legend"}
      </button>
      <div className={cn(!open && "hidden lg:block")}>
        <label className="flex items-center gap-2 font-medium text-foreground">
          <input type="checkbox" className="size-3.5 accent-[var(--accent)]" checked={showAlerts} onChange={(e) => onAlerts(e.target.checked)} />
          <Siren size={12} aria-hidden="true" /> Area markers
        </label>
        <p className="ms-6 mt-1 text-faint">
          Size: {measure}
          {period ? ` · ${period.toLowerCase()}` : ""}
        </p>
        <p className="ms-6 text-faint">Approximate area position</p>
        <ul className="ms-6 mt-1.5 grid grid-cols-2 gap-x-2 gap-y-1 text-muted">
          <li className="flex items-center gap-1.5">
            <span aria-hidden="true" className="size-2.5 rounded-full bg-accent" /> No active alert
          </li>
          {SEVERITY_ORDER.map((s) => (
            <li key={s} className="flex items-center gap-1.5">
              <span aria-hidden="true" className="size-2.5 rounded-full" style={{ background: `var(${SEVERITY_META[s].token})` }} />
              {SEVERITY_META[s].label}
            </li>
          ))}
          <li className="col-span-2 flex items-center gap-1.5">
            <span aria-hidden="true" className="size-2.5 rounded-full border-2 border-accent bg-transparent" /> Value suppressed (small numbers)
          </li>
          <li className="col-span-2 flex items-center gap-1.5">
            <span aria-hidden="true" className="size-3 rounded-full border-[3px] border-[var(--map-selected)] bg-transparent" /> Selected area or facility
          </li>
        </ul>
        <label className="mt-3 flex items-center gap-2 font-medium text-foreground">
          <input type="checkbox" className="size-3.5 accent-[var(--accent)]" checked={showFacilities} onChange={(e) => onFacilities(e.target.checked)} />
          <Building2 size={12} aria-hidden="true" /> Care facilities
        </label>
        {facilityCount !== null && (
          <p className="ms-6 mt-0.5 text-faint" title={register ? registerTitle(register) : undefined}>
            {facilityCountText(facilityCount, register)}
          </p>
        )}
        <ul className="ms-6 mt-1 space-y-0.5 text-muted">
          <li className="flex items-center gap-1.5">
            <span aria-hidden="true" className="size-2 rounded-full bg-[var(--map-label)]" /> Hospital
            <span aria-hidden="true" className="ms-2 size-1.5 rounded-full bg-[var(--map-facility-other)]" /> Centre / clinic
          </li>
          {excluded ? <li className="text-faint">{excluded} without usable coordinates not shown</li> : null}
        </ul>
      </div>
    </div>
  );
}

function SeverityBadge({ severity }: { severity: keyof typeof SEVERITY_META }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium text-foreground"
      style={{ borderColor: `var(${SEVERITY_META[severity].token})` }}
    >
      <span aria-hidden="true" className="size-1.5 rounded-full" style={{ background: `var(${SEVERITY_META[severity].token})` }} />
      {SEVERITY_META[severity].label}
    </span>
  );
}

function AreaRow({ area, metric, severity, onSelect }: { area: MapAreaOut; metric: MapMetric; severity?: keyof typeof SEVERITY_META; onSelect: () => void }) {
  return (
    <li>
      <button type="button" onClick={onSelect} className="group flex w-full items-center gap-3 px-5 py-2.5 text-start transition-colors hover:bg-hover">
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm text-foreground">{area.area.name}</span>
          <span className="flex items-center gap-2 text-[11px] text-faint">
            {area.active_alerts > 0 && severity ? <SeverityBadge severity={severity} /> : null}
            {!area.representative_point && <span>unmapped</span>}
          </span>
        </span>
        <span className="text-end text-sm font-semibold tabular-nums text-foreground">{metricText(metric, area.metric_value)}</span>
      </button>
    </li>
  );
}

function AreaDetail({
  area,
  metric,
  context,
  alerts,
  onClose,
}: {
  area: MapAreaOut;
  metric: MapMetric;
  context: AreaContext;
  alerts: { alert_id: string; severity: keyof typeof SEVERITY_META; title: string; explanation: string }[];
  onClose: () => void;
}) {
  const rows: [string, string][] = [
    ["Registered population", metricText("population", area.population)],
    ["Open care gaps", metricText("open_care_gaps", area.open_care_gaps)],
    ["Preventive coverage", metricText("preventive_coverage", area.preventive_coverage)],
    ["Care facilities", area.care_facilities === null ? "Unknown" : String(area.care_facilities)],
  ];
  if (area.disease) {
    rows.push([`New diagnoses · ${area.disease.condition_name ?? ""}`, metricText("new_cases", area.disease.new_cases ?? null)]);
    rows.push(["Prevalence", metricText("prevalence", area.disease.prevalence ?? null)]);
  }
  const trend = area.disease?.trend?.direction;
  const suppressed = suppressedLabels(area.suppressed ?? []);
  const rp = area.representative_point;
  return (
    <div className="reveal-fade flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="flex items-start justify-between gap-2 border-b border-border px-5 py-3">
        <div className="min-w-0">
          <button type="button" onClick={onClose} className="mb-1 inline-flex items-center gap-1 text-xs text-accent hover:underline">
            <ArrowLeft size={12} aria-hidden="true" className="rtl:rotate-180" /> Back to all areas
          </button>
          <p className="text-xs text-faint">{area.area.level === "district" ? "District" : "Local area"}</p>
          <h3 className="text-lg font-semibold text-foreground">{area.area.name}</h3>
          <p className="mt-0.5 text-xs text-muted">
            {context.period ?? "Current period"} · as of {context.asOf}
          </p>
        </div>
        <button type="button" aria-label="Clear area selection" onClick={onClose} className="rounded-full p-1.5 text-muted hover:bg-hover hover:text-foreground">
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <dl className="grid grid-cols-2 gap-3 px-5 py-4">
        {rows.map(([k, v]) => (
          <div key={k} className={cn("rounded-lg bg-surface-sunken px-3 py-2", k.startsWith(METRICS.find((m) => m.value === metric)?.label ?? "~") && "ring-1 ring-accent")}>
            <dt className="text-[11px] text-muted">{k}</dt>
            <dd className="figure mt-0.5 text-lg text-foreground">{v}</dd>
          </div>
        ))}
        {trend && (
          <div className="col-span-2 rounded-lg bg-surface-sunken px-3 py-2">
            <dt className="text-[11px] text-muted">Trend · {area.disease?.condition_name ?? "condition"}</dt>
            <dd className="mt-0.5 text-sm text-foreground">{trend.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}</dd>
          </div>
        )}
      </dl>
      <div className="space-y-1.5 px-5 text-xs text-faint">
        {suppressed.length > 0 && <p className="text-muted">Suppressed: {suppressed.join(", ")}</p>}
        {area.facility_association !== "matched" && area.care_facilities === null && (
          <p>No published facility label matches this area, so its facility coverage is unknown (not zero).</p>
        )}
        <p>
          {rp
            ? `Approximate area position: median of ${rp.facility_count} published facility locations.`
            : "Not mapped — fewer than 3 published facility locations."}
        </p>
        <p>
          Synthetic patient records, aggregated server-side
          {context.minCellSize !== null ? `; suppressed below ${context.minCellSize}` : "; small numbers suppressed"}.
        </p>
      </div>
      <div className="px-5 py-4">
        <h4 className="mb-2 text-xs font-medium text-muted">Active alerts</h4>
        {alerts.length === 0 ? (
          <p className="text-sm text-muted">No active alerts for this area.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {alerts.map((a) => (
              <li key={a.alert_id} className="rounded-lg border border-border p-3">
                <SeverityBadge severity={a.severity} />
                <p className="mt-1.5 text-sm font-medium text-foreground">{a.title}</p>
                <p className="mt-0.5 text-xs text-muted">{a.explanation}</p>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-[11px] text-faint">Threshold-based signals on synthetic data — not confirmed outbreaks.</p>
      </div>
    </div>
  );
}

function FacilityPanel({ resource, onClose }: { resource: Resource<FacilityDetailOut | null>; onClose: () => void }) {
  return (
    <div className="reveal-fade flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="flex items-center justify-between gap-2 border-b border-border px-5 py-2">
        <p className="text-xs text-faint">Care facility</p>
        <button type="button" aria-label="Clear facility selection" onClick={onClose} className="rounded-full p-1.5 text-muted hover:bg-hover hover:text-foreground">
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <div className="min-h-0 flex-1 px-5 py-4">
        <ResourceView resource={resource} what="Facility records">
          {(d) => (d ? <FacilityDetail facility={d} /> : <FacilityNotFound onClose={onClose} />)}
        </ResourceView>
      </div>
    </div>
  );
}

function FacilityNotFound({ onClose }: { onClose: () => void }) {
  return (
    <div role="status" className="flex flex-col items-start gap-2 text-sm text-muted">
      <p className="font-medium text-foreground">Facility not found in the published register</p>
      <p className="text-xs">It may have been removed from the register or is not mapped. Nothing is shown in its place.</p>
      <button type="button" onClick={onClose} className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
        <ArrowLeft size={12} aria-hidden="true" className="rtl:rotate-180" /> Back to all areas
      </button>
    </div>
  );
}

function FacilityDetail({ facility: d }: { facility: FacilityDetailOut }) {
  const type = [d.source_layer ? FACILITY_LAYER_META[d.source_layer]?.label : null, d.facility_type, d.subtype]
    .filter((v, i, a): v is string => Boolean(v) && a.indexOf(v) === i)
    .join(" · ");
  const place = [d.city, d.region_id !== null ? regionLabel(d.region_id) : null].filter(Boolean).join(" · ");
  const coords = coordinateText(d.latitude, d.longitude);
  const rows: [string, React.ReactNode][] = [
    ["Type", type || "—"],
    ["Location", place || "—"],
    ["Sector", sectorLabel(d.is_public)],
    ["Licence status", d.license_status ?? "—"],
    ["Licence no.", d.license_no ?? "—"],
    [
      "Coordinates",
      coords ? (
        <span dir="ltr" className="tabular-nums">
          {coords}
        </span>
      ) : (
        "—"
      ),
    ],
    ["Coordinate quality", geoQualityLabel(d.geo_quality)],
    ...publishedServiceFlags(d),
    ["Source effective date", d.source_effective_date ?? "—"],
  ];
  return (
    <div className="flex flex-col gap-3">
      <div>
        <h3 className="text-lg font-semibold text-foreground">{d.facility_name ?? "Unnamed facility"}</h3>
        {d.facility_name_ar && (
          <p dir="rtl" lang="ar" className="text-sm text-muted">
            {d.facility_name_ar}
          </p>
        )}
      </div>
      <dl className="divide-y divide-border rounded-lg border border-border">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-start justify-between gap-3 px-3 py-2 text-sm">
            <dt className="shrink-0 text-xs text-muted">{k}</dt>
            <dd className="min-w-0 text-end text-foreground">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-muted">{NOT_PUBLISHED}</p>
      {d.governance_notice && <p className="text-[11px] text-faint">{d.governance_notice}</p>}
      {d.ch_fid && (
        <Link href={`/facilities?facility=${encodeURIComponent(d.ch_fid)}`} className={cn(buttonClass("secondary"), "self-start")}>
          <ExternalLink size={14} aria-hidden="true" className="rtl:-scale-x-100" /> Open in facility directory
        </Link>
      )}
    </div>
  );
}
