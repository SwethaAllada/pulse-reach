"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { MapPin, Search, X } from "lucide-react";
import { api } from "@/lib/api/client";
import { cached } from "@/lib/api/cache";
import { useResource } from "@/lib/api/resource";
import type { FacilityDetailOut, FacilityPointOut } from "@/lib/api/geo-types";
import { useAuth } from "@/lib/auth/auth-context";
import { REGION_OPTIONS, regionLabel } from "@/lib/population/filters";
import { FACILITY_LAYER_META } from "@/lib/population/geo";
import { PageHeader } from "@/components/ui/page-header";
import { Plate } from "@/components/ui/plate";
import { KpiCard } from "@/components/ui/figure";
import { buttonClass } from "@/components/ui/button-styles";
import { ResourceView } from "@/components/programmes/resource-state";
import { Pager, QuietEmpty, compactInputClass } from "@/components/coordination/primitives";
import { cn } from "@/lib/cn";

const PAGE = 50;

export type FacilitySort = "name" | "city" | "type";
const SORTS: { value: FacilitySort; label: string }[] = [
  { value: "name", label: "Name" },
  { value: "city", label: "City" },
  { value: "type", label: "Type" },
];

interface RegisterState {
  q: string;
  type: string;
  region: string;
  sort: FacilitySort;
  page: number;
  facility: string;
}

function readState(p: URLSearchParams | { get: (k: string) => string | null }): RegisterState {
  const sort = p.get("sort");
  const page = Number(p.get("page"));
  return {
    q: p.get("q") ?? "",
    type: p.get("type") && FACILITY_LAYER_META[p.get("type")!] ? p.get("type")! : "",
    region: p.get("region") ?? "",
    sort: sort === "city" || sort === "type" ? sort : "name",
    page: Number.isInteger(page) && page > 1 ? page : 1,
    facility: p.get("facility") ?? "",
  };
}

function toQuery(s: RegisterState): string {
  const p = new URLSearchParams();
  if (s.q) p.set("q", s.q);
  if (s.type) p.set("type", s.type);
  if (s.region) p.set("region", s.region);
  if (s.sort !== "name") p.set("sort", s.sort);
  if (s.page > 1) p.set("page", String(s.page));
  if (s.facility) p.set("facility", s.facility);
  return p.toString();
}

export const mapHref = (chFid: string) => `/population?facility=${encodeURIComponent(chFid)}`;

const typeLabel = (f: { source_layer: string | null; facility_type: string | null }) =>
  FACILITY_LAYER_META[f.source_layer ?? ""]?.label ?? f.facility_type ?? "—";
const sectorLabel = (isPublic: boolean | null) => (isPublic === null ? "Unknown" : isPublic ? "Public" : "Private");
const byText = (a: string | null, b: string | null) => {
  if (!a && !b) return 0;
  if (!a) return 1; // missing values sort last
  if (!b) return -1;
  return a.localeCompare(b);
};

/** Filters and sorts the mappable register (pure; memoized by the caller). */
export function filterFacilities(items: FacilityPointOut[], s: Pick<RegisterState, "q" | "type" | "region" | "sort">): FacilityPointOut[] {
  const needle = s.q.trim().toLowerCase();
  const out = items.filter(
    (f) =>
      (!s.type || f.source_layer === s.type) &&
      (!s.region || String(f.region_id) === s.region) &&
      (!needle || (f.name ?? "").toLowerCase().includes(needle) || (f.city ?? "").toLowerCase().includes(needle))
  );
  const name = (a: FacilityPointOut, b: FacilityPointOut) => byText(a.name, b.name);
  const cmp =
    s.sort === "city"
      ? (a: FacilityPointOut, b: FacilityPointOut) => byText(a.city, b.city) || name(a, b)
      : s.sort === "type"
        ? (a: FacilityPointOut, b: FacilityPointOut) => byText(typeLabel(a), typeLabel(b)) || name(a, b)
        : name;
  return out.sort(cmp);
}

/** Published SDI care-facility register (hospitals, health centres, clinics with usable coordinates). */
export function FacilityRegister() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { can } = useAuth();
  const canMap = can("population.read");
  const [attempt, setAttempt] = useState(0);
  const [s, setS] = useState<RegisterState>(() => readState(params));
  const panelRef = useRef<HTMLElement | null>(null);

  const points = useResource("facility-register", "facilities.read", () => cached("facility-points", () => api.facilityPoints()), attempt);

  const update = (patch: Partial<RegisterState>, resetPage = true) => {
    const next = { ...s, ...(resetPage ? { page: 1 } : {}), ...patch };
    setS(next);
    const qs = toQuery(next);
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    return next;
  };
  const openFacility = (id: string) => {
    update({ facility: id }, false);
    requestAnimationFrame(() => panelRef.current?.focus());
  };

  const all = points.status === "ready" ? points.data.items : null;
  const { q, type, region, sort } = s;
  const items = useMemo(() => (all ? filterFacilities(all, { q, type, region, sort }) : []), [all, q, type, region, sort]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of all ?? []) c[f.source_layer ?? ""] = (c[f.source_layer ?? ""] ?? 0) + 1;
    return c;
  }, [all]);
  const pages = Math.max(1, Math.ceil(items.length / PAGE));
  const page = Math.min(s.page, pages);
  const filtered = !!(s.q || s.type || s.region);
  const register = points.status === "ready" ? points.data.register : undefined;

  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <PageHeader
        title="Facilities"
        subtitle="The published Abu Dhabi SDI register of hospitals, health centres and clinics. Licence records — not verified operating status, capacity or services."
        breadcrumbs={[{ label: "Facilities" }]}
      />
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {register && <KpiCard label="Published register" value={register.register_total} note="all published SDI records" />}
        <KpiCard label="Listed & mapped" value={points.status === "ready" ? points.data.total : "…"} note="Active licence · valid coordinates" />
        {Object.entries(FACILITY_LAYER_META).map(([k, m]) => (
          <KpiCard key={k} label={`${m.label}s`} value={all ? (counts[k] ?? 0) : "…"} note="listed & mapped" />
        ))}
      </dl>
      <div className={cn("grid gap-6", s.facility && "lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start")}>
        <Plate
          title="Register"
          flush
          actions={
            <span className="flex w-full flex-wrap gap-2 sm:w-auto">
              <span className="relative w-full sm:w-56">
                <Search size={14} aria-hidden="true" className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-faint" />
                <input
                  type="search"
                  aria-label="Search by name or city"
                  placeholder="Name or city"
                  className={cn(compactInputClass, "w-full ps-8")}
                  value={s.q}
                  onChange={(e) => update({ q: e.target.value })}
                />
              </span>
              <select aria-label="Facility type" className={cn(compactInputClass, "w-40")} value={s.type} onChange={(e) => update({ type: e.target.value })}>
                <option value="">All types</option>
                {Object.entries(FACILITY_LAYER_META).map(([k, m]) => (
                  <option key={k} value={k}>
                    {m.label}s
                  </option>
                ))}
              </select>
              <select aria-label="Region" className={cn(compactInputClass, "w-36")} value={s.region} onChange={(e) => update({ region: e.target.value })}>
                <option value="">All regions</option>
                {REGION_OPTIONS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
              <select aria-label="Sort by" className={cn(compactInputClass, "w-32")} value={s.sort} onChange={(e) => update({ sort: e.target.value as FacilitySort })}>
                {SORTS.map((o) => (
                  <option key={o.value} value={o.value}>
                    Sort: {o.label}
                  </option>
                ))}
              </select>
            </span>
          }
        >
          <ResourceView resource={points} what="Facilities" onRetry={() => setAttempt((a) => a + 1)}>
            {(d) => (
              <>
                <p className="px-5 pt-3 text-xs text-muted" aria-live="polite">
                  Showing {items.length.toLocaleString("en")} of {d.total.toLocaleString("en")}
                </p>
                {items.length === 0 ? (
                  <div className="px-5 py-4">
                    <QuietEmpty title="No facilities match these filters">
                      Try a different name or city, or widen the type and region.
                    </QuietEmpty>
                    {filtered && (
                      <div className="mt-3 flex justify-center">
                        <button type="button" className={buttonClass("secondary")} onClick={() => update({ q: "", type: "", region: "" })}>
                          Clear filters
                        </button>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[640px] text-sm">
                      <thead className="text-start text-xs text-muted">
                        <tr className="border-b border-border">
                          <th className="px-5 py-2.5 text-start font-medium">Facility</th>
                          <th className="px-5 py-2.5 text-start font-medium">Type</th>
                          <th className="px-5 py-2.5 text-start font-medium">City · region</th>
                          <th className="px-5 py-2.5 text-start font-medium">Sector</th>
                          <th className="px-5 py-2.5 text-start font-medium">Licence</th>
                          {canMap && (
                            <th className="px-5 py-2.5 text-start font-medium">
                              <span className="sr-only">Map</span>
                            </th>
                          )}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {items.slice((page - 1) * PAGE, page * PAGE).map((f, i) => {
                          const selected = !!f.ch_fid && f.ch_fid === s.facility;
                          const name = f.name ?? "Unnamed facility";
                          return (
                            <tr key={f.ch_fid ?? i} className={cn("hover:bg-hover", selected && "bg-hover")}>
                              <td className="px-5 py-2.5 text-foreground">
                                {f.ch_fid ? (
                                  <button
                                    type="button"
                                    className="rounded text-start font-medium text-foreground underline-offset-4 hover:underline focus-visible:underline"
                                    aria-pressed={selected}
                                    onClick={() => openFacility(f.ch_fid!)}
                                  >
                                    {name}
                                  </button>
                                ) : (
                                  name
                                )}
                              </td>
                              <td className="px-5 py-2.5 text-muted">{typeLabel(f)}</td>
                              <td className="px-5 py-2.5 text-muted">
                                {f.city ?? "—"} · {f.region_id ? regionLabel(f.region_id) : "—"}
                              </td>
                              <td className="px-5 py-2.5 text-muted">{sectorLabel(f.is_public)}</td>
                              <td className="px-5 py-2.5 text-muted">{f.license_status ?? "—"}</td>
                              {canMap && (
                                <td className="px-3 py-1.5 text-end">
                                  {f.ch_fid && (
                                    <Link
                                      href={mapHref(f.ch_fid)}
                                      aria-label={`Show ${name} on map`}
                                      title="Show on map"
                                      className="inline-flex size-8 items-center justify-center rounded-full text-muted hover:bg-surface-raised hover:text-foreground"
                                    >
                                      <MapPin size={15} aria-hidden="true" />
                                    </Link>
                                  )}
                                </td>
                              )}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="px-5 pb-4">
                  <Pager page={page} total={items.length} size={PAGE} onPage={(p) => update({ page: p }, false)} label="Facilities" />
                  <p className="mt-3 text-[11px] text-faint">
                    {d.governance_notice}{" "}
                    {register
                      ? `${register.in_layers.toLocaleString("en")} hospital/health-centre/clinic records: ${register.excluded_license_status.toLocaleString("en")} without an Active licence and ${register.excluded_invalid_coordinates.toLocaleString("en")} without valid coordinates are not listed.`
                      : `Only hospitals, health centres and clinics with an Active licence are listed.${d.excluded_without_coordinates > 0 ? ` ${d.excluded_without_coordinates.toLocaleString("en")} records without usable coordinates are not listed.` : ""}`}
                    {!canMap && " The map is available to roles with population access."}
                  </p>
                </div>
              </>
            )}
          </ResourceView>
        </Plate>
        {s.facility && (
          <FacilityDetailPanel key={s.facility} id={s.facility} canMap={canMap} panelRef={panelRef} onClose={() => update({ facility: "" }, false)} />
        )}
      </div>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{children}</dd>
    </div>
  );
}

const yesNo = (v: boolean) => (v ? "Yes" : "No");

function FacilityDetailPanel({
  id,
  canMap,
  panelRef,
  onClose,
}: {
  id: string;
  canMap: boolean;
  panelRef: React.RefObject<HTMLElement | null>;
  onClose: () => void;
}) {
  const [attempt, setAttempt] = useState(0);
  const detail = useResource(`facility-detail|${id}`, "facilities.read", (signal) => api.facilityDetail(id, signal), attempt);
  return (
    <section
      ref={panelRef}
      tabIndex={-1}
      aria-label="Facility details"
      className="reveal min-w-0 rounded-xl border border-border bg-surface-raised outline-none lg:sticky lg:top-20"
    >
      <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
        <h2 className="text-[15px] font-semibold text-foreground">
          {detail.status === "ready" ? (detail.data.facility_name ?? "Unnamed facility") : "Facility details"}
        </h2>
        <button type="button" aria-label="Close facility details" onClick={onClose} className={buttonClass("quiet", "shrink-0 text-muted")}>
          <X size={16} aria-hidden="true" />
        </button>
      </header>
      <div className="px-5 py-4">
        <ResourceView resource={detail} what="Facility details" onRetry={() => setAttempt((a) => a + 1)}>
          {(d) => <FacilityFacts d={d} canMap={canMap} id={id} />}
        </ResourceView>
      </div>
    </section>
  );
}

function FacilityFacts({ d, canMap, id }: { d: FacilityDetailOut; canMap: boolean; id: string }) {
  const flags: [string, boolean | null][] = [
    ["Emergency department", d.emergency_department],
    ["Paediatric emergency", d.pediatric_emergency_department],
    ["Maternity emergency care", d.maternity_emergency_care],
    ["Home care services", d.home_care_services],
  ];
  const published = flags.filter((f): f is [string, boolean] => f[1] !== null);
  const coords = d.latitude !== null && d.longitude !== null;
  const type = [FACILITY_LAYER_META[d.source_layer ?? ""]?.label ?? d.facility_type, d.subtype].filter(Boolean).join(" · ");
  return (
    <div className="flex flex-col gap-4">
      {d.facility_name_ar && (
        <p dir="rtl" lang="ar" className="text-sm text-foreground">
          {d.facility_name_ar}
        </p>
      )}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Fact label="Type">{type || "—"}</Fact>
        <Fact label="City · region">
          {d.city ?? "—"} · {d.region_id ? regionLabel(d.region_id) : "—"}
        </Fact>
        <Fact label="Sector">{sectorLabel(d.is_public)}</Fact>
        <Fact label="Licence">
          {d.license_status ?? "—"}
          {d.license_no && <span className="block text-xs text-muted">No. {d.license_no}</span>}
        </Fact>
        <Fact label="Coordinates">
          {coords ? (
            <span dir="ltr" className="tabular-nums">
              {d.latitude!.toFixed(5)}, {d.longitude!.toFixed(5)}
            </span>
          ) : (
            "Not published"
          )}
          {d.geo_quality && <span className="block text-xs text-muted">Quality: {d.geo_quality}</span>}
        </Fact>
        {d.source_effective_date && <Fact label="Source effective date">{d.source_effective_date}</Fact>}
        {published.map(([label, v]) => (
          <Fact key={label} label={label}>
            {yesNo(v)}
          </Fact>
        ))}
        {d.inpatient_bed_capacity !== null && <Fact label="Inpatient beds">{d.inpatient_bed_capacity.toLocaleString("en")}</Fact>}
      </dl>
      {d.specialities_raw && (
        <dl>
          <Fact label="Published specialities (unverified)">{d.specialities_raw}</Fact>
        </dl>
      )}
      <p className="text-xs text-muted">
        Published licence record — opening hours, contact details, appointment availability and referral acceptance are not published and are not
        shown.
      </p>
      {d.governance_notice && <p className="text-[11px] text-faint">{d.governance_notice}</p>}
      {canMap ? (
        <Link href={mapHref(d.ch_fid ?? id)} className={buttonClass("secondary", "self-start")}>
          <MapPin size={14} aria-hidden="true" /> Show on map
        </Link>
      ) : (
        <p className="text-xs text-muted">The map is available to roles with population access.</p>
      )}
    </div>
  );
}
