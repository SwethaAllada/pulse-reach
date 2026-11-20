"use client";

import Link from "next/link";
import { ArrowRight, KeyRound, Link2, ScrollText, ShieldCheck, UserCog } from "lucide-react";
import { adminApi, api } from "@/lib/api/client";
import { useResource, type Resource } from "@/lib/api/resource";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDateTime } from "@/lib/coordination/model";
import { PageHeader } from "@/components/ui/page-header";
import { Plate } from "@/components/ui/plate";
import { KpiCard } from "@/components/ui/figure";
import { ResourceView } from "@/components/programmes/resource-state";
import { AuditTable } from "./admin-pages";

const ROLES = ["SYSTEM_ADMIN", "POPULATION_HEALTH_MANAGER", "CARE_COORDINATOR", "CLINICIAN", "PATIENT"] as const;
const ROLE_NAMES: Record<string, string> = {
  SYSTEM_ADMIN: "System administrators",
  POPULATION_HEALTH_MANAGER: "Population health managers",
  CARE_COORDINATOR: "Care coordinators",
  CLINICIAN: "Clinicians",
  PATIENT: "Patients",
};

function num<T>(r: Resource<T>, pick: (d: T) => number | string): number | string {
  return r.status === "ready" ? pick(r.data) : r.status === "loading" ? "…" : "—";
}

/** System administrator home: accounts, access and audit for the organization — never patient data. */
export function AdminOverview() {
  const { can } = useAuth();
  const users = useResource(can("users.read") ? "adm-users" : null, "users.read", (s) => adminApi.users({ limit: 1, offset: 0 }, s), 0);
  const byRole = useResource(
    can("users.read") ? "adm-by-role" : null,
    "users.read",
    (s) => Promise.all(ROLES.map((role) => adminApi.users({ role, limit: 1, offset: 0 }, s).then((p) => [role, p.total] as const))),
    0
  );
  const links = useResource(
    can("patient_links.manage") ? "adm-links" : null,
    "patient_links.manage",
    (s) => adminApi.patientLinks({ status: "active", limit: 1, offset: 0 }, s),
    0
  );
  const assignments = useResource(
    can("assignments.manage") ? "adm-assign" : null,
    "assignments.manage",
    (s) => adminApi.assignments({ active_only: true, limit: 1, offset: 0 }, s),
    0
  );
  const denied = useResource(
    can("audit_logs.read") ? "adm-denied" : null,
    "audit_logs.read",
    (s) => adminApi.auditEvents({ outcome: "denied", limit: 1, offset: 0 }, s),
    0
  );
  const recent = useResource(can("audit_logs.read") ? "adm-recent" : null, "audit_logs.read", (s) => adminApi.auditEvents({ limit: 8, offset: 0 }, s), 0);
  const updates = useResource(
    can("population.refresh") ? "adm-updates" : null,
    "population.refresh",
    (s) => api.populationUpdates(s),
    0
  );
  const maxRole = byRole.status === "ready" ? Math.max(1, ...byRole.data.map(([, n]) => n)) : 1;

  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow="System administration"
        title="Administration"
        subtitle="Accounts, roles, care-team access, patient portal links and the audit trail for your organization. Administrators see no patient records."
      />
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        <KpiCard label="Accounts" value={num(users, (d) => d.total)} note="staff and patient members" i={0} />
        <KpiCard label="Active assignments" value={num(assignments, (d) => d.total)} note="staff ↔ patient" i={1} />
        <KpiCard label="Portal links" value={num(links, (d) => d.total)} note="active patient accounts" i={2} />
        <KpiCard label="Denied requests" value={num(denied, (d) => d.total)} note="in the audit log" i={3} />
        <KpiCard
          label="Population aggregation"
          value={num(updates, (d) => (d.stale ? "Stale" : d.aggregation_status === "succeeded" ? "Current" : d.aggregation_status.replace(/_/g, " ")))}
          note={updates.status === "ready" && updates.data.last_aggregation_at ? `last run ${formatDateTime(updates.data.last_aggregation_at)}` : "latest run"}
          i={4}
        />
      </dl>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Plate title="Recent audit activity" description="Newest first; denied and failed outcomes are highlighted." actions={<More href="/admin/audit">Audit log</More>} flush>
          <ResourceView resource={recent} what="Audit events">
            {(p) => <AuditTable events={p.items} />}
          </ResourceView>
        </Plate>
        <div className="flex flex-col gap-4">
          <Plate title="Members by role">
            <ResourceView resource={byRole} what="Role counts">
              {(rows) => (
                <ul className="flex flex-col gap-3">
                  {rows.map(([role, n]) => (
                    <li key={role}>
                      <div className="flex justify-between text-sm">
                        <span className="text-muted">{ROLE_NAMES[role]}</span>
                        <span className="font-semibold tabular-nums text-foreground">{n}</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded-full bg-surface-sunken">
                        <div className="grow-x h-1.5 rounded-full bg-accent" style={{ width: `${(n / maxRole) * 100}%` }} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </ResourceView>
          </Plate>
          <Plate title="Manage" flush>
            <ul className="divide-y divide-border text-sm">
              {[
                { href: "/admin/users", icon: UserCog, label: "Users & roles", perm: "users.read" },
                { href: "/admin/assignments", icon: Link2, label: "Care-team assignments", perm: "assignments.manage" },
                { href: "/admin/patient-links", icon: KeyRound, label: "Patient portal links", perm: "patient_links.manage" },
                { href: "/admin/audit", icon: ScrollText, label: "Audit log", perm: "audit_logs.read" },
                { href: "/admin/population", icon: ShieldCheck, label: "Population aggregation", perm: "population.refresh" },
              ]
                .filter((x) => can(x.perm))
                .map(({ href, icon: Icon, label }) => (
                  <li key={href}>
                    <Link href={href} className="group flex items-center gap-3 px-5 py-3 text-foreground transition-colors hover:bg-hover">
                      <Icon size={16} aria-hidden="true" className="text-accent" />
                      <span className="flex-1">{label}</span>
                      <ArrowRight size={14} aria-hidden="true" className="text-faint transition-transform group-hover:translate-x-0.5" />
                    </Link>
                  </li>
                ))}
            </ul>
          </Plate>
        </div>
      </div>
    </div>
  );
}

function More({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="inline-flex items-center gap-1 text-[13px] font-medium text-accent hover:underline">
      {children} <ArrowRight size={13} aria-hidden="true" />
    </Link>
  );
}
