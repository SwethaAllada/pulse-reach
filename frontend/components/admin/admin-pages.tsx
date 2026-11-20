"use client";

import { useState } from "react";
import { Copy, Plus, RefreshCw } from "lucide-react";
import { adminApi, api, apiErrorMessage } from "@/lib/api/client";
import { useResource } from "@/lib/api/resource";
import type { AssignableRole, AuditEventOut, OneTimeTokenOut, PatientAccess } from "@/lib/api/admin-types";
import { useAuth } from "@/lib/auth/auth-context";
import { ROLE_LABELS, formatDateTime } from "@/lib/coordination/model";
import { PageHeader } from "@/components/ui/page-header";
import { Plate, Footnote } from "@/components/ui/plate";
import { KpiCard } from "@/components/ui/figure";
import { buttonClass } from "@/components/ui/button-styles";
import { ResourceView } from "@/components/programmes/resource-state";
import { Confirmation, FormError, Pager, QuietEmpty, StatusPill, compactInputClass, inputClass, labelClass } from "@/components/coordination/primitives";
import { cn } from "@/lib/cn";

const PAGE = 25;
const CRUMBS = (label: string) => [{ label: "Administration", href: "/" }, { label }];

function Shell({ title, subtitle, actions, children }: { title: string; subtitle: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <PageHeader title={title} subtitle={subtitle} breadcrumbs={CRUMBS(title)} actions={actions} />
      {children}
    </div>
  );
}

/** Runs a write, reporting pending/error, and bumps `onDone` so lists refetch. */
function useWrite(onDone: () => void) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    setPending(true);
    setError(null);
    try {
      const out = await fn();
      onDone();
      return out;
    } catch (err) {
      setError(apiErrorMessage(err));
      return null;
    } finally {
      setPending(false);
    }
  };
  return { run, pending, error };
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={cn("px-5 py-2.5 font-medium", right && "text-right")}>{children}</th>;
}

function Table({ head, children }: { head: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted">
          <tr className="border-b border-border">{head}</tr>
        </thead>
        <tbody className="divide-y divide-border">{children}</tbody>
      </table>
    </div>
  );
}

function OneTimeCode({ token, label }: { token: OneTimeTokenOut; label: string }) {
  return (
    <Confirmation>
      <span className="font-medium">{label}</span> Hand this single-use code to the person through an approved channel — PulseReach sends no
      e-mail or SMS. Expires {formatDateTime(token.expires_at)}.
      <span className="mt-2 flex items-center gap-2">
        <code className="rounded-md bg-surface-raised px-2 py-1 font-mono text-sm">{token.token}</code>
        <button type="button" className={buttonClass("quiet")} onClick={() => void navigator.clipboard?.writeText(token.token)}>
          <Copy size={13} aria-hidden="true" /> Copy
        </button>
      </span>
    </Confirmation>
  );
}

/* ── Users & roles ─────────────────────────────────────────────────────── */

export function UsersAdmin() {
  const { can, state } = useAuth();
  const selfId = state.status === "signed_in" ? state.me.user.user_id : null;
  const [page, setPage] = useState(1);
  const [role, setRole] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const [code, setCode] = useState<{ token: OneTimeTokenOut; label: string } | null>(null);
  const bump = () => setAttempt((n) => n + 1);
  const users = useResource(`users|${role}|${page}|${attempt}`, "users.read", (s) => adminApi.users({ role: role || undefined, limit: PAGE, offset: (page - 1) * PAGE }, s), attempt);
  const w = useWrite(bump);

  return (
    <Shell
      title="Users & roles"
      subtitle="Staff accounts in your organization, their role and patient access. New accounts receive a one-time activation code."
      actions={
        can("users.create") && !creating ? (
          <button type="button" className={buttonClass("primary")} onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden="true" /> New staff account
          </button>
        ) : undefined
      }
    >
      {creating && <CreateUser onCancel={() => setCreating(false)} onCreated={(t, name) => (setCreating(false), setCode({ token: t, label: `Account created for ${name}.` }), bump())} />}
      {code && <OneTimeCode {...code} />}
      <FormError message={w.error} />
      <Plate
        title="Members"
        flush
        actions={
          <select aria-label="Filter by role" className={cn(compactInputClass, "w-56")} value={role} onChange={(e) => (setRole(e.target.value), setPage(1))}>
            <option value="">All roles</option>
            {Object.entries(ROLE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        }
      >
        <ResourceView resource={users} what="Users" onRetry={bump}>
          {(p) => (
            <>
              <Table head={<><Th>Name</Th><Th>Role</Th><Th>Patient access</Th><Th>Status</Th><Th right>Actions</Th></>}>
                {p.items.map((u) => {
                  const active = u.account_active && u.membership_active;
                  const self = u.user_id === selfId;
                  return (
                    <tr key={u.user_id} className="hover:bg-hover">
                      <td className="px-5 py-3">
                        <span className="block font-medium text-foreground">{u.full_name}</span>
                        <span className="text-xs text-faint">{u.email}</span>
                      </td>
                      <td className="px-5 py-3">
                        {can("users.update") && !self && u.role !== "PATIENT" ? (
                          <select
                            aria-label={`Role for ${u.full_name}`}
                            className={cn(compactInputClass, "w-52")}
                            value={u.role}
                            disabled={w.pending}
                            onChange={(e) => void w.run(() => adminApi.updateUser(u.user_id, { role: e.target.value as AssignableRole }))}
                          >
                            {(["SYSTEM_ADMIN", "POPULATION_HEALTH_MANAGER", "CARE_COORDINATOR", "CLINICIAN"] as const).map((r) => (
                              <option key={r} value={r}>
                                {ROLE_LABELS[r]}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="text-muted">{ROLE_LABELS[u.role] ?? u.role}</span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-muted">{u.role === "PATIENT" ? "Own record" : u.patient_access === "organization" ? "Whole organization" : "Assigned only"}</td>
                      <td className="px-5 py-3">
                        <StatusPill tone={active ? "completed" : "not_eligible"} label={active ? (u.password_set ? "Active" : "Awaiting activation") : "Deactivated"} />
                      </td>
                      <td className="px-5 py-3 text-right">
                        {!self && u.role !== "PATIENT" && (
                          <span className="inline-flex gap-1">
                            {can("users.update") && (
                              <button
                                type="button"
                                className={buttonClass("quiet")}
                                disabled={w.pending}
                                onClick={async () => {
                                  const t = await w.run(() => adminApi.issuePasswordReset(u.user_id));
                                  if (t) setCode({ token: t, label: `Reset code for ${u.full_name}.` });
                                }}
                              >
                                Reset code
                              </button>
                            )}
                            {can("users.deactivate") && (
                              <button
                                type="button"
                                className={buttonClass("quiet", active ? "text-status-error" : undefined)}
                                disabled={w.pending}
                                onClick={() => {
                                  if (!active || window.confirm(`Deactivate ${u.full_name}? Their sessions end immediately.`))
                                    void w.run(() => adminApi.setUserActive(u.user_id, !active));
                                }}
                              >
                                {active ? "Deactivate" : "Activate"}
                              </button>
                            )}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </Table>
              <div className="px-5 pb-4">
                <Pager page={page} total={p.total} size={PAGE} onPage={setPage} label="Users" />
              </div>
            </>
          )}
        </ResourceView>
      </Plate>
    </Shell>
  );
}

function CreateUser({ onCancel, onCreated }: { onCancel: () => void; onCreated: (t: OneTimeTokenOut, name: string) => void }) {
  const [form, setForm] = useState({ full_name: "", email: "", role: "CARE_COORDINATOR" as AssignableRole, patient_access: "assigned" as PatientAccess });
  const w = useWrite(() => {});
  const valid = form.full_name.trim() && /.+@.+\..+/.test(form.email.trim());
  return (
    <form
      aria-label="New staff account"
      className="reveal rounded-xl border border-border bg-surface-raised p-5"
      onSubmit={async (e) => {
        e.preventDefault();
        const out = await w.run(() => adminApi.createUser({ ...form, full_name: form.full_name.trim(), email: form.email.trim() }));
        if (out) onCreated(out.activation, out.member.full_name);
      }}
    >
      <h2 className="text-[15px] font-semibold text-foreground">New staff account</h2>
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className={labelClass}>
          Full name
          <input className={inputClass} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required />
        </label>
        <label className={labelClass}>
          Work e-mail
          <input type="email" className={inputClass} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
        </label>
        <label className={labelClass}>
          Role
          <select className={inputClass} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as AssignableRole })}>
            {(["CARE_COORDINATOR", "CLINICIAN", "POPULATION_HEALTH_MANAGER", "SYSTEM_ADMIN"] as const).map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          Patient access
          <select className={inputClass} value={form.patient_access} onChange={(e) => setForm({ ...form, patient_access: e.target.value as PatientAccess })}>
            <option value="assigned">Assigned patients only</option>
            <option value="organization">Whole organization</option>
          </select>
        </label>
      </div>
      <div className="mt-4">
        <FormError message={w.error} />
      </div>
      <div className="mt-4 flex gap-2">
        <button type="submit" className={buttonClass("primary")} disabled={!valid || w.pending}>
          {w.pending ? "Creating…" : "Create account"}
        </button>
        <button type="button" className={buttonClass("secondary")} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/* ── Care-team assignments ─────────────────────────────────────────────── */

export function AssignmentsAdmin() {
  const [page, setPage] = useState(1);
  const [activeOnly, setActiveOnly] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const bump = () => setAttempt((n) => n + 1);
  const list = useResource(`asg|${activeOnly}|${page}|${attempt}`, "assignments.manage", (s) => adminApi.assignments({ active_only: activeOnly, limit: PAGE, offset: (page - 1) * PAGE }, s), attempt);
  const staff = useResource(`asg-staff|${attempt}`, "assignments.manage", (s) => adminApi.assignableStaff(s), attempt);
  const names = new Map(staff.status === "ready" ? staff.data.map((u) => [u.user_id, u.full_name]) : []);
  const [form, setForm] = useState({ staff: "", patient: "" });
  const w = useWrite(bump);

  return (
    <Shell title="Care-team assignments" subtitle="Which staff member may see which patient. Staff with “assigned only” access see just these patients.">
      <form
        aria-label="New assignment"
        className="reveal flex flex-wrap items-end gap-3 rounded-xl border border-border bg-surface-raised p-4"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await w.run(() => adminApi.createAssignment(form.staff, form.patient.trim()))) setForm({ staff: form.staff, patient: "" });
        }}
      >
        <label className={cn(labelClass, "w-64")}>
          Staff member
          <select className={inputClass} value={form.staff} onChange={(e) => setForm({ ...form, staff: e.target.value })}>
            <option value="">Select…</option>
            {staff.status === "ready" &&
              staff.data.map((u) => (
                <option key={u.user_id} value={u.user_id}>
                  {u.full_name} · {ROLE_LABELS[u.role] ?? u.role}
                </option>
              ))}
          </select>
        </label>
        <label className={cn(labelClass, "w-56")}>
          Synthetic patient ID
          <input className={cn(inputClass, "font-mono")} placeholder="SYNTH-PAT-000001" value={form.patient} onChange={(e) => setForm({ ...form, patient: e.target.value })} />
        </label>
        <button type="submit" className={buttonClass("primary")} disabled={!form.staff || !form.patient.trim() || w.pending}>
          <Plus size={15} aria-hidden="true" /> Assign
        </button>
        <div className="w-full empty:hidden">
          <FormError message={w.error} />
        </div>
      </form>
      <Plate
        title="Assignments"
        flush
        actions={
          <label className="flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={activeOnly} onChange={(e) => (setActiveOnly(e.target.checked), setPage(1))} />
            Active only
          </label>
        }
      >
        <ResourceView resource={list} what="Assignments" onRetry={bump}>
          {(p) =>
            p.items.length === 0 ? (
              <div className="p-5">
                <QuietEmpty title="No assignments" />
              </div>
            ) : (
              <>
                <Table head={<><Th>Staff member</Th><Th>Patient</Th><Th>Since</Th><Th>Status</Th><Th right>Actions</Th></>}>
                  {p.items.map((a) => (
                    <tr key={a.assignment_id} className="hover:bg-hover">
                      <td className="px-5 py-3 text-foreground">{names.get(a.staff_user_id) ?? a.staff_user_id}</td>
                      <td className="px-5 py-3 font-mono text-muted">{a.patient_id}</td>
                      <td className="px-5 py-3 text-muted">{formatDateTime(a.created_at)}</td>
                      <td className="px-5 py-3">
                        <StatusPill tone={a.is_active ? "completed" : "not_eligible"} label={a.is_active ? "Active" : "Ended"} />
                      </td>
                      <td className="px-5 py-3 text-right">
                        {a.is_active && (
                          <button
                            type="button"
                            className={buttonClass("quiet", "text-status-error")}
                            disabled={w.pending}
                            onClick={() => window.confirm("End this assignment? The staff member loses access to this patient.") && void w.run(() => adminApi.endAssignment(a.assignment_id))}
                          >
                            End
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </Table>
                <div className="px-5 pb-4">
                  <Pager page={page} total={p.total} size={PAGE} onPage={setPage} label="Assignments" />
                </div>
              </>
            )
          }
        </ResourceView>
      </Plate>
    </Shell>
  );
}

/* ── Patient portal links ──────────────────────────────────────────────── */

export function PatientLinksAdmin() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<"" | "active" | "revoked">("active");
  const [attempt, setAttempt] = useState(0);
  const bump = () => setAttempt((n) => n + 1);
  const list = useResource(`links|${status}|${page}|${attempt}`, "patient_links.manage", (s) => adminApi.patientLinks({ status: status || undefined, limit: PAGE, offset: (page - 1) * PAGE }, s), attempt);
  const w = useWrite(bump);
  return (
    <Shell title="Patient portal links" subtitle="Verified links between patient accounts and their synthetic record. Revoking ends the patient’s portal access.">
      <FormError message={w.error} />
      <Plate
        title="Links"
        flush
        actions={
          <select aria-label="Link status" className={cn(compactInputClass, "w-40")} value={status} onChange={(e) => (setStatus(e.target.value as typeof status), setPage(1))}>
            <option value="active">Active</option>
            <option value="revoked">Revoked</option>
            <option value="">All</option>
          </select>
        }
      >
        <ResourceView resource={list} what="Patient links" onRetry={bump}>
          {(p) =>
            p.items.length === 0 ? (
              <div className="p-5">
                <QuietEmpty title="No links" />
              </div>
            ) : (
              <>
                <Table head={<><Th>Patient</Th><Th>Verified</Th><Th>Method</Th><Th>Status</Th><Th right>Actions</Th></>}>
                  {p.items.map((l) => (
                    <tr key={l.link_id} className="hover:bg-hover">
                      <td className="px-5 py-3 font-mono text-foreground">{l.patient_id}</td>
                      <td className="px-5 py-3 text-muted">{formatDateTime(l.verified_at)}</td>
                      <td className="px-5 py-3 text-muted">{l.verification_method.replace(/_/g, " ")}</td>
                      <td className="px-5 py-3">
                        <StatusPill tone={l.status === "active" ? "completed" : "not_eligible"} label={l.status === "active" ? "Active" : "Revoked"} />
                      </td>
                      <td className="px-5 py-3 text-right">
                        {l.status === "active" && (
                          <button
                            type="button"
                            className={buttonClass("quiet", "text-status-error")}
                            disabled={w.pending}
                            onClick={() => window.confirm("Revoke this link? The patient can no longer open the portal.") && void w.run(() => adminApi.revokePatientLink(l.link_id))}
                          >
                            Revoke
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </Table>
                <div className="px-5 pb-4">
                  <Pager page={page} total={p.total} size={PAGE} onPage={setPage} label="Links" />
                </div>
              </>
            )
          }
        </ResourceView>
      </Plate>
    </Shell>
  );
}

/* ── Audit log ─────────────────────────────────────────────────────────── */

export function AuditTable({ events }: { events: AuditEventOut[] }) {
  if (events.length === 0) return <p className="px-5 py-4 text-sm text-muted">No audit events.</p>;
  return (
    <Table head={<><Th>When</Th><Th>Action</Th><Th>Actor</Th><Th>Resource</Th><Th right>Outcome</Th></>}>
      {events.map((e) => (
        <tr key={e.event_id} className="hover:bg-hover">
          <td className="whitespace-nowrap px-5 py-2.5 text-muted">{formatDateTime(e.occurred_at)}</td>
          <td className="px-5 py-2.5 font-mono text-xs text-foreground">{e.action}</td>
          <td className="px-5 py-2.5 text-muted">{e.actor_role ? (ROLE_LABELS[e.actor_role] ?? e.actor_role) : "—"}</td>
          <td className="px-5 py-2.5 text-xs text-muted">
            {e.resource_type}
            {e.resource_id && <span className="block max-w-[220px] truncate font-mono text-faint">{e.resource_id}</span>}
          </td>
          <td className="px-5 py-2.5 text-right">
            <StatusPill
              tone={e.outcome === "success" ? "completed" : e.outcome === "denied" ? "due" : "insufficient"}
              label={`${e.outcome === "success" ? "Success" : e.outcome === "denied" ? "Denied" : "Failed"}${e.status_code ? ` · ${e.status_code}` : ""}`}
            />
          </td>
        </tr>
      ))}
    </Table>
  );
}

export function AuditAdmin() {
  const [page, setPage] = useState(1);
  const [outcome, setOutcome] = useState<"" | "success" | "denied" | "failed">("");
  const [action, setAction] = useState("");
  const list = useResource(`audit|${outcome}|${action}|${page}`, "audit_logs.read", (s) => adminApi.auditEvents({ outcome: outcome || undefined, action: action || undefined, limit: PAGE, offset: (page - 1) * PAGE }, s), 0);
  return (
    <Shell title="Audit log" subtitle="Every access decision and change in your organization. Notes and message text are never recorded here.">
      <Plate
        title="Events"
        flush
        actions={
          <span className="flex flex-wrap gap-2">
            <input aria-label="Action contains" placeholder="Action, e.g. user.update" className={cn(compactInputClass, "w-56 font-mono text-xs")} value={action} onChange={(e) => (setAction(e.target.value.trim()), setPage(1))} />
            <select aria-label="Outcome" className={cn(compactInputClass, "w-36")} value={outcome} onChange={(e) => (setOutcome(e.target.value as typeof outcome), setPage(1))}>
              <option value="">All outcomes</option>
              <option value="success">Success</option>
              <option value="denied">Denied</option>
              <option value="failed">Failed</option>
            </select>
          </span>
        }
      >
        <ResourceView resource={list} what="Audit events">
          {(p) => (
            <>
              <AuditTable events={p.items} />
              <div className="px-5 pb-4">
                <Pager page={page} total={p.total} size={PAGE} onPage={setPage} label="Audit" />
              </div>
            </>
          )}
        </ResourceView>
      </Plate>
    </Shell>
  );
}

/* ── Population aggregation ────────────────────────────────────────────── */

export function PopulationAdmin() {
  const { can } = useAuth();
  const [attempt, setAttempt] = useState(0);
  const bump = () => setAttempt((n) => n + 1);
  const updates = useResource(can("population.refresh") ? `pop-upd|${attempt}` : null, "population.refresh", (s) => api.populationUpdates(s), attempt);
  const config = useResource(`pop-cfg|${attempt}`, "population.configure", (s) => api.populationConfig(s), attempt);
  const w = useWrite(bump);
  const [done, setDone] = useState(false);
  return (
    <Shell
      title="Population aggregation"
      subtitle="The persisted surveillance snapshot behind population metrics, hotspots and alerts, and the thresholds it uses."
      actions={
        can("population.refresh") ? (
          <button type="button" className={buttonClass("primary")} disabled={w.pending} onClick={async () => setDone(!!(await w.run(() => api.refreshPopulation())))}>
            <RefreshCw size={15} aria-hidden="true" className={w.pending ? "animate-spin" : undefined} /> {w.pending ? "Refreshing…" : "Refresh now"}
          </button>
        ) : undefined
      }
    >
      <FormError message={w.error} />
      {done && !w.error && <Confirmation>Aggregation refreshed. The action was recorded in the audit log.</Confirmation>}
      <ResourceView resource={updates} what="Aggregation status" onRetry={bump}>
        {(u) => (
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <KpiCard label="Status" value={u.stale ? "Stale" : u.aggregation_status.replace(/_/g, " ")} note={u.data_changed_since_aggregation ? "data changed since the last run" : "no unprocessed changes"} />
            <KpiCard label="Last run" value={u.last_aggregation_at ? formatDateTime(u.last_aggregation_at) : "Never"} size="md" note={u.latest_run?.trigger ? `trigger: ${u.latest_run.trigger.replace(/_/g, " ")}` : undefined} />
            <KpiCard label="Snapshot age" value={u.staleness_seconds === null ? "—" : `${Math.round(u.staleness_seconds / 60)} min`} />
            <KpiCard label="Data complete through" value={u.latest_run?.complete_through ?? "—"} size="md" note="reporting delay applied" />
          </dl>
        )}
      </ResourceView>
      <Plate title="Thresholds" description="Demonstration values for the synthetic dataset — not DoH or clinical targets.">
        <ResourceView resource={config} what="Threshold configuration" onRetry={bump}>
          {(c) => (
            <>
              <p className="mb-3 text-sm text-muted">
                Version {c.version}
                {c.is_default ? " (defaults)" : ""} · small-cell suppression below {c.min_cell_size}
                {c.updated_at ? ` · updated ${formatDateTime(c.updated_at)}` : ""}
              </p>
              <pre className="max-h-[420px] overflow-auto rounded-lg bg-surface-sunken p-4 font-mono text-xs leading-relaxed text-foreground">
                {JSON.stringify(c.thresholds, null, 2)}
              </pre>
              <Footnote>Threshold changes are made through `PATCH /population/config` and trigger an immediate, audited refresh.</Footnote>
            </>
          )}
        </ResourceView>
      </Plate>
    </Shell>
  );
}
