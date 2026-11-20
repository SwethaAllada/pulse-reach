"use client";

import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { api } from "@/lib/api/client";
import { cached } from "@/lib/api/cache";
import { useResource } from "@/lib/api/resource";
import { REGION_OPTIONS, regionLabel } from "@/lib/population/filters";
import { FACILITY_LAYER_META } from "@/lib/population/geo";
import { PageHeader } from "@/components/ui/page-header";
import { Plate } from "@/components/ui/plate";
import { KpiCard } from "@/components/ui/figure";
import { ResourceView } from "@/components/programmes/resource-state";
import { Pager, compactInputClass } from "@/components/coordination/primitives";
import { cn } from "@/lib/cn";

const PAGE = 50;

/** Published SDI care-facility register (hospitals, health centres, clinics with usable coordinates). */
export function FacilityRegister() {
  const points = useResource("facility-register", "facilities.read", () => cached("facility-points", () => api.facilityPoints()), 0);
  const [q, setQ] = useState("");
  const [layer, setLayer] = useState("");
  const [region, setRegion] = useState("");
  const [page, setPage] = useState(1);
  const items = useMemo(() => {
    if (points.status !== "ready") return [];
    const needle = q.trim().toLowerCase();
    return points.data.items
      .filter((f) => (!layer || f.source_layer === layer) && (!region || String(f.region_id) === region))
      .filter((f) => !needle || `${f.name ?? ""} ${f.city ?? ""}`.toLowerCase().includes(needle))
      .sort((a, b) => (a.name ?? "").localeCompare(b.name ?? ""));
  }, [points, q, layer, region]);
  const count = (l: string) => (points.status === "ready" ? points.data.items.filter((f) => f.source_layer === l).length : "…");
  const reset = (fn: () => void) => (fn(), setPage(1));

  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <PageHeader
        title="Facilities"
        subtitle="The published Abu Dhabi SDI register of hospitals, health centres and clinics. Licence records — not verified operating status, capacity or services."
        breadcrumbs={[{ label: "Facilities" }]}
      />
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KpiCard label="Care facilities" value={points.status === "ready" ? points.data.total : "…"} note="with usable coordinates" />
        {Object.entries(FACILITY_LAYER_META).map(([k, m]) => (
          <KpiCard key={k} label={`${m.label}s`} value={count(k)} note="published records" />
        ))}
      </dl>
      <Plate
        title="Register"
        flush
        actions={
          <span className="flex flex-wrap gap-2">
            <span className="relative">
              <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
              <input aria-label="Search by name or city" placeholder="Name or city" className={cn(compactInputClass, "w-56 pl-8")} value={q} onChange={(e) => reset(() => setQ(e.target.value))} />
            </span>
            <select aria-label="Facility type" className={cn(compactInputClass, "w-40")} value={layer} onChange={(e) => reset(() => setLayer(e.target.value))}>
              <option value="">All types</option>
              {Object.entries(FACILITY_LAYER_META).map(([k, m]) => (
                <option key={k} value={k}>
                  {m.label}s
                </option>
              ))}
            </select>
            <select aria-label="Region" className={cn(compactInputClass, "w-36")} value={region} onChange={(e) => reset(() => setRegion(e.target.value))}>
              <option value="">All regions</option>
              {REGION_OPTIONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </span>
        }
      >
        <ResourceView resource={points} what="Facilities">
          {(d) => (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted">
                    <tr className="border-b border-border">
                      <th className="px-5 py-2.5 font-medium">Facility</th>
                      <th className="px-5 py-2.5 font-medium">Type</th>
                      <th className="px-5 py-2.5 font-medium">City · region</th>
                      <th className="px-5 py-2.5 font-medium">Sector</th>
                      <th className="px-5 py-2.5 font-medium">Licence</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {items.slice((page - 1) * PAGE, page * PAGE).map((f, i) => (
                      <tr key={f.ch_fid ?? i} className="hover:bg-hover">
                        <td className="px-5 py-2.5 text-foreground">{f.name ?? "Unnamed facility"}</td>
                        <td className="px-5 py-2.5 text-muted">{FACILITY_LAYER_META[f.source_layer ?? ""]?.label ?? f.facility_type}</td>
                        <td className="px-5 py-2.5 text-muted">
                          {f.city ?? "—"} · {f.region_id ? regionLabel(f.region_id) : "—"}
                        </td>
                        <td className="px-5 py-2.5 text-muted">{f.is_public === null ? "Unknown" : f.is_public ? "Public" : "Private"}</td>
                        <td className="px-5 py-2.5 text-muted">{f.license_status ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {items.length === 0 && <p className="px-5 py-4 text-sm text-muted">No facilities match.</p>}
              </div>
              <div className="px-5 pb-4">
                <Pager page={page} total={items.length} size={PAGE} onPage={setPage} label="Facilities" />
                <p className="mt-3 text-[11px] text-faint">
                  {d.governance_notice} {d.excluded_without_coordinates > 0 && `${d.excluded_without_coordinates} records without usable coordinates are not listed.`}
                </p>
              </div>
            </>
          )}
        </ResourceView>
      </Plate>
    </div>
  );
}
