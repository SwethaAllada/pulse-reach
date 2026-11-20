"use client";

import { useState } from "react";
import { Copy, Plus, RefreshCw } from "lucide-react";
import { adminApi, api, apiErrorMessage } from "@/lib/api/client";
import { useResource } from "@/lib/api/resource";
import type { AssignableRole, AuditEventOut, OneTimeTokenOut, PatientAccess } from "@/lib/api/admin-types";
import { useAuth } from "@/lib/auth/auth-context";
import { formatDateTime } from "@/lib/coordination/model";
import { PageHeader } from "@/components/ui/page-header";
import { Plate, Footnote } from "@/components/ui/plate";
import { KpiCard } from "@/components/ui/figure";
import { buttonClass } from "@/components/ui/button-styles";
import { ResourceView } from "@/components/programmes/resource-state";
import { Confirmation, FormError, Pager, QuietEmpty, StatusPill, compactInputClass, inputClass, labelClass } from "@/components/coordination/primitives";
import { cn } from "@/lib/cn";
import { useLocale } from "@/lib/i18n/use-locale";
import type { Translate } from "@/lib/i18n/translate";

const PAGE = 25;
const ROLES = ["SYSTEM_ADMIN", "POPULATION_HEALTH_MANAGER", "CARE_COORDINATOR", "CLINICIAN", "PATIENT"] as const;

function adminRoleLabel(role: string, t: Translate): string {
  if (role === "SYSTEM_ADMIN") return t("admin.role_admin");
  return (ROLES as readonly string[]).includes(role) ? t(`role.${role as (typeof ROLES)[number]}`) : role;
}

function Shell({ title, subtitle, actions, children }: { title: string; subtitle: string; actions?: React.ReactNode; children: React.ReactNode }) {
  const { t } = useLocale();
  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <PageHeader title={title} subtitle={subtitle} breadcrumbs={[{ label: t("nav.administration"), href: "/" }, { label: title }]} actions={actions} />
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
  return <th className={cn("px-5 py-2.5 font-medium", right && "text-end")}>{children}</th>;
}

function Table({ head, children }: { head: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-start text-xs text-muted">
          <tr className="border-b border-border">{head}</tr>
        </thead>
        <tbody className="divide-y divide-border">{children}</tbody>
      </table>
    </div>
  );
}

function OneTimeCode({ token, label }: { token: OneTimeTokenOut; label: string }) {
  const { t, rich } = useLocale();
  return (
    <Confirmation>
      {rich("admin.code.body", { label: <span className="font-medium">{label}</span>, expires: formatDateTime(token.expires_at) })}
      <span className="mt-2 flex items-center gap-2">
        <code className="ltr-value rounded-md bg-surface-raised px-2 py-1 font-mono text-sm">{token.token}</code>
        <button type="button" className={buttonClass("quiet")} onClick={() => void navigator.clipboard?.writeText(token.token)}>
          <Copy size={13} aria-hidden="true" /> {t("admin.code.copy")}
        </button>
      </span>
    </Confirmation>
  );
}

/* ── Users & roles ─────────────────────────────────────────────────────── */

export function UsersAdmin() {
  const { can, state } = useAuth();
  const { t } = useLocale();
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
      title={t("nav.users_roles")}
      subtitle={t("admin.users.subtitle")}
      actions={
        can("users.create") && !creating ? (
          <button type="button" className={buttonClass("primary")} onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden="true" /> {t("admin.users.new")}
          </button>
        ) : undefined
      }
    >
      {creating && <CreateUser onCancel={() => setCreating(false)} onCreated={(tok, name) => (setCreating(false), setCode({ token: tok, label: t("admin.code.created", { name }) }), bump())} />}
      {code && <OneTimeCode {...code} />}
      <FormError message={w.error} />
      <Plate
        title={t("admin.users.members")}
        flush
        actions={
          <select aria-label={t("admin.users.filter_role")} className={cn(compactInputClass, "w-56")} value={role} onChange={(e) => (setRole(e.target.value), setPage(1))}>
            <option value="">{t("admin.users.all_roles")}</option>
            {ROLES.map((k) => (
              <option key={k} value={k}>
                {adminRoleLabel(k, t)}
              </option>
            ))}
          </select>
        }
      >
        <ResourceView resource={users} what={t("admin.what.users")} onRetry={bump}>
          {(p) => (
            <>
              <Table
                head={
                  <>
                    <Th>{t("admin.col.name")}</Th>
                    <Th>{t("admin.col.role")}</Th>
                    <Th>{t("admin.col.patient_access")}</Th>
                    <Th>{t("admin.col.status")}</Th>
                    <Th right>{t("admin.col.actions")}</Th>
                  </>
                }
              >
                {p.items.map((u) => {
                  const active = u.account_active && u.membership_active;
                  const self = u.user_id === selfId;
                  return (
                    <tr key={u.user_id} className="hover:bg-hover">
                      <td className="px-5 py-3">
                        <span className="block font-medium text-foreground">{u.full_name}</span>
                        <span className="ltr-value text-xs text-faint">{u.email}</span>
                      </td>
                      <td className="px-5 py-3">
                        {can("users.update") && !self && u.role !== "PATIENT" ? (
                          <select
                            aria-label={t("admin.users.role_for", { name: u.full_name })}
                            className={cn(compactInputClass, "w-52")}
                            value={u.role}
                            disabled={w.pending}
                            onChange={(e) => void w.run(() => adminApi.updateUser(u.user_id, { role: e.target.value as AssignableRole }))}
                          >
                            {(["SYSTEM_ADMIN", "POPULATION_HEALTH_MANAGER", "CARE_COORDINATOR", "CLINICIAN"] as const).map((r) => (
                              <option key={r} value={r}>
                                {adminRoleLabel(r, t)}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="text-muted">{adminRoleLabel(u.role, t)}</span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-muted">{u.role === "PATIENT"
                          ? t("admin.users.access_own")
                          : u.patient_access === "organization"
                            ? t("admin.users.access_org")
                            : t("admin.users.access_assigned")}</td>
                      <td className="px-5 py-3">
                        <StatusPill tone={active ? "completed" : "not_eligible"} label={active ? (u.password_set ? t("admin.status.active") : t("admin.status.awaiting")) : t("admin.status.deactivated")} />
                      </td>
                      <td className="px-5 py-3 text-end">
                        {!self && u.role !== "PATIENT" && (
                          <span className="inline-flex gap-1">
                            {can("users.update") && (
                              <button
                                type="button"
                                className={buttonClass("quiet")}
                                disabled={w.pending}
                                onClick={async () => {
                                  const tok = await w.run(() => adminApi.issuePasswordReset(u.user_id));
                                  if (tok) setCode({ token: tok, label: t("admin.code.reset", { name: u.full_name }) });
                                }}
                              >
                                {t("admin.users.reset_code")}
                              </button>
                            )}
                            {can("users.deactivate") && (
                              <button
                                type="button"
                                className={buttonClass("quiet", active ? "text-status-error" : undefined)}
                                disabled={w.pending}
                                onClick={() => {
                                  if (!active || window.confirm(t("admin.users.confirm_deactivate", { name: u.full_name })))
                                    void w.run(() => adminApi.setUserActive(u.user_id, !active));
                                }}
                              >
                                {active ? t("admin.users.deactivate") : t("admin.users.activate")}
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
                <Pager page={page} total={p.total} size={PAGE} onPage={setPage} label={t("admin.pager.users")} />
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
  const { t } = useLocale();
  const w = useWrite(() => {});
  const valid = form.full_name.trim() && /.+@.+\..+/.test(form.email.trim());
  return (
    <form
      aria-label={t("admin.users.new")}
      className="reveal rounded-xl border border-border bg-surface-raised p-5"
      onSubmit={async (e) => {
        e.preventDefault();
        const out = await w.run(() => adminApi.createUser({ ...form, full_name: form.full_name.trim(), email: form.email.trim() }));
        if (out) onCreated(out.activation, out.member.full_name);
      }}
    >
      <h2 className="text-[15px] font-semibold text-foreground">{t("admin.users.new")}</h2>
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className={labelClass}>
          {t("admin.users.full_name")}
          <input className={inputClass} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required />
        </label>
        <label className={labelClass}>
          {t("admin.users.email")}
          <input type="email" dir="ltr" className={inputClass} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
        </label>
        <label className={labelClass}>
          {t("admin.col.role")}
          <select className={inputClass} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as AssignableRole })}>
            {(["CARE_COORDINATOR", "CLINICIAN", "POPULATION_HEALTH_MANAGER", "SYSTEM_ADMIN"] as const).map((r) => (
              <option key={r} value={r}>
                {adminRoleLabel(r, t)}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          {t("admin.col.patient_access")}
          <select className={inputClass} value={form.patient_access} onChange={(e) => setForm({ ...form, patient_access: e.target.value as PatientAccess })}>
            <option value="assigned">{t("admin.users.access_assigned_only")}</option>
            <option value="organization">{t("admin.users.access_org")}</option>
          </select>
        </label>
      </div>
      <div className="mt-4">
        <FormError message={w.error} />
      </div>
      <div className="mt-4 flex gap-2">
        <button type="submit" className={buttonClass("primary")} disabled={!valid || w.pending}>
          {w.pending ? t("admin.users.creating") : t("admin.users.create")}
        </button>
        <button type="button" className={buttonClass("secondary")} onClick={onCancel}>
          {t("admin.users.cancel")}
        </button>
      </div>
    </form>
  );
}

/* ── Care-team assignments ─────────────────────────────────────────────── */

export function AssignmentsAdmin() {
  const [page, setPage] = useState(1);
  const { t } = useLocale();
  const [activeOnly, setActiveOnly] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const bump = () => setAttempt((n) => n + 1);
  const list = useResource(`asg|${activeOnly}|${page}|${attempt}`, "assignments.manage", (s) => adminApi.assignments({ active_only: activeOnly, limit: PAGE, offset: (page - 1) * PAGE }, s), attempt);
  const staff = useResource(`asg-staff|${attempt}`, "assignments.manage", (s) => adminApi.assignableStaff(s), attempt);
  const names = new Map(staff.status === "ready" ? staff.data.map((u) => [u.user_id, u.full_name]) : []);
  const [form, setForm] = useState({ staff: "", patient: "" });
  const w = useWrite(bump);

  return (
    <Shell title={t("nav.care_team_assignments")} subtitle={t("admin.asg.subtitle")}>
      <form
        aria-label={t("admin.asg.new")}
        className="reveal flex flex-wrap items-end gap-3 rounded-xl border border-border bg-surface-raised p-4"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await w.run(() => adminApi.createAssignment(form.staff, form.patient.trim()))) setForm({ staff: form.staff, patient: "" });
        }}
      >
        <label className={cn(labelClass, "w-64")}>
          {t("admin.col.staff")}
          <select className={inputClass} value={form.staff} onChange={(e) => setForm({ ...form, staff: e.target.value })}>
            <option value="">{t("admin.asg.select")}</option>
            {staff.status === "ready" &&
              staff.data.map((u) => (
                <option key={u.user_id} value={u.user_id}>
                  {u.full_name} · {adminRoleLabel(u.role, t)}
                </option>
              ))}
          </select>
        </label>
        <label className={cn(labelClass, "w-56")}>
          {t("admin.asg.patient_id")}
          <input dir="ltr" className={cn(inputClass, "font-mono")} placeholder="SYNTH-PAT-000001" value={form.patient} onChange={(e) => setForm({ ...form, patient: e.target.value })} />
        </label>
        <button type="submit" className={buttonClass("primary")} disabled={!form.staff || !form.patient.trim() || w.pending}>
          <Plus size={15} aria-hidden="true" /> {t("admin.asg.assign")}
        </button>
        <div className="w-full empty:hidden">
          <FormError message={w.error} />
        </div>
      </form>
      <Plate
        title={t("admin.asg.title")}
        flush
        actions={
          <label className="flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={activeOnly} onChange={(e) => (setActiveOnly(e.target.checked), setPage(1))} />
            {t("admin.asg.active_only")}
          </label>
        }
      >
        <ResourceView resource={list} what={t("admin.what.assignments")} onRetry={bump}>
          {(p) =>
            p.items.length === 0 ? (
              <div className="p-5">
                <QuietEmpty title={t("admin.asg.empty")} />
              </div>
            ) : (
              <>
                <Table
                  head={
                    <>
                      <Th>{t("admin.col.staff")}</Th>
                      <Th>{t("admin.col.patient")}</Th>
                      <Th>{t("admin.col.since")}</Th>
                      <Th>{t("admin.col.status")}</Th>
                      <Th right>{t("admin.col.actions")}</Th>
                    </>
                  }
                >
                  {p.items.map((a) => (
                    <tr key={a.assignment_id} className="hover:bg-hover">
                      <td className="px-5 py-3 text-foreground">{names.get(a.staff_user_id) ?? a.staff_user_id}</td>
                      <td className="px-5 py-3 font-mono text-muted">
                        <span className="ltr-value">{a.patient_id}</span>
                      </td>
                      <td className="px-5 py-3 text-muted">{formatDateTime(a.created_at)}</td>
                      <td className="px-5 py-3">
                        <StatusPill tone={a.is_active ? "completed" : "not_eligible"} label={a.is_active ? t("admin.status.active") : t("admin.status.ended")} />
                      </td>
                      <td className="px-5 py-3 text-end">
                        {a.is_active && (
                          <button
                            type="button"
                            className={buttonClass("quiet", "text-status-error")}
                            disabled={w.pending}
                            onClick={() => window.confirm(t("admin.asg.confirm_end")) && void w.run(() => adminApi.endAssignment(a.assignment_id))}
                          >
                            {t("admin.asg.end")}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </Table>
                <div className="px-5 pb-4">
                  <Pager page={page} total={p.total} size={PAGE} onPage={setPage} label={t("admin.pager.assignments")} />
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
  const { t } = useLocale();
  const [status, setStatus] = useState<"" | "active" | "revoked">("active");
  const [attempt, setAttempt] = useState(0);
  const bump = () => setAttempt((n) => n + 1);
  const list = useResource(`links|${status}|${page}|${attempt}`, "patient_links.manage", (s) => adminApi.patientLinks({ status: status || undefined, limit: PAGE, offset: (page - 1) * PAGE }, s), attempt);
  const w = useWrite(bump);
  return (
    <Shell title={t("nav.patient_portal_links")} subtitle={t("admin.links.subtitle")}>
      <FormError message={w.error} />
      <Plate
        title={t("admin.links.title")}
        flush
        actions={
          <select aria-label={t("admin.links.status")} className={cn(compactInputClass, "w-40")} value={status} onChange={(e) => (setStatus(e.target.value as typeof status), setPage(1))}>
            <option value="active">{t("admin.status.active")}</option>
            <option value="revoked">{t("admin.status.revoked")}</option>
            <option value="">{t("admin.links.all")}</option>
          </select>
        }
      >
        <ResourceView resource={list} what={t("admin.what.links")} onRetry={bump}>
          {(p) =>
            p.items.length === 0 ? (
              <div className="p-5">
                <QuietEmpty title={t("admin.links.empty")} />
              </div>
            ) : (
              <>
                <Table
                  head={
                    <>
                      <Th>{t("admin.col.patient")}</Th>
                      <Th>{t("admin.col.verified")}</Th>
                      <Th>{t("admin.col.method")}</Th>
                      <Th>{t("admin.col.status")}</Th>
                      <Th right>{t("admin.col.actions")}</Th>
                    </>
                  }
                >
                  {p.items.map((l) => (
                    <tr key={l.link_id} className="hover:bg-hover">
                      <td className="px-5 py-3 font-mono text-foreground">
                        <span className="ltr-value">{l.patient_id}</span>
                      </td>
                      <td className="px-5 py-3 text-muted">{formatDateTime(l.verified_at)}</td>
                      <td className="px-5 py-3 text-muted">
                        <span className="ltr-value">{l.verification_method.replace(/_/g, " ")}</span>
                      </td>
                      <td className="px-5 py-3">
                        <StatusPill tone={l.status === "active" ? "completed" : "not_eligible"} label={l.status === "active" ? t("admin.status.active") : t("admin.status.revoked")} />
                      </td>
                      <td className="px-5 py-3 text-end">
                        {l.status === "active" && (
                          <button
                            type="button"
                            className={buttonClass("quiet", "text-status-error")}
                            disabled={w.pending}
                            onClick={() => window.confirm(t("admin.links.confirm_revoke")) && void w.run(() => adminApi.revokePatientLink(l.link_id))}
                          >
                            {t("admin.links.revoke")}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </Table>
                <div className="px-5 pb-4">
                  <Pager page={page} total={p.total} size={PAGE} onPage={setPage} label={t("admin.pager.links")} />
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
  const { t } = useLocale();
  if (events.length === 0) return <p className="px-5 py-4 text-sm text-muted">{t("admin.audit.empty")}</p>;
  const outcomeLabel = (o: AuditEventOut["outcome"]) =>
    o === "success" ? t("admin.audit.success") : o === "denied" ? t("admin.audit.denied") : t("admin.audit.failed");
  return (
    <Table
      head={
        <>
          <Th>{t("admin.col.when")}</Th>
          <Th>{t("admin.col.action")}</Th>
          <Th>{t("admin.col.actor")}</Th>
          <Th>{t("admin.col.resource")}</Th>
          <Th right>{t("admin.col.outcome")}</Th>
        </>
      }
    >
      {events.map((e) => (
        <tr key={e.event_id} className="hover:bg-hover">
          <td className="whitespace-nowrap px-5 py-2.5 text-muted">{formatDateTime(e.occurred_at)}</td>
          <td className="px-5 py-2.5 font-mono text-xs text-foreground">
            <span className="ltr-value">{e.action}</span>
          </td>
          <td className="px-5 py-2.5 text-muted">{e.actor_role ? adminRoleLabel(e.actor_role, t) : "—"}</td>
          <td className="px-5 py-2.5 text-xs text-muted">
            <span className="ltr-value">{e.resource_type}</span>
            {e.resource_id && <span className="ltr-value block max-w-[220px] truncate font-mono text-faint">{e.resource_id}</span>}
          </td>
          <td className="px-5 py-2.5 text-end">
            <StatusPill
              tone={e.outcome === "success" ? "completed" : e.outcome === "denied" ? "due" : "insufficient"}
              label={`${outcomeLabel(e.outcome)}${e.status_code ? ` · ${e.status_code}` : ""}`}
            />
          </td>
        </tr>
      ))}
    </Table>
  );
}

export function AuditAdmin() {
  const [page, setPage] = useState(1);
  const { t } = useLocale();
  const [outcome, setOutcome] = useState<"" | "success" | "denied" | "failed">("");
  const [action, setAction] = useState("");
  const list = useResource(`audit|${outcome}|${action}|${page}`, "audit_logs.read", (s) => adminApi.auditEvents({ outcome: outcome || undefined, action: action || undefined, limit: PAGE, offset: (page - 1) * PAGE }, s), 0);
  return (
    <Shell title={t("nav.audit_log")} subtitle={t("admin.audit.subtitle")}>
      <Plate
        title={t("admin.audit.events")}
        flush
        actions={
          <span className="flex flex-wrap gap-2">
            <input
              aria-label={t("admin.audit.action_contains")}
              placeholder={t("admin.audit.action_placeholder")}
              className={cn(compactInputClass, "w-56 font-mono text-xs")} value={action} onChange={(e) => (setAction(e.target.value.trim()), setPage(1))} />
            <select aria-label={t("admin.col.outcome")} className={cn(compactInputClass, "w-36")} value={outcome} onChange={(e) => (setOutcome(e.target.value as typeof outcome), setPage(1))}>
              <option value="">{t("admin.audit.all_outcomes")}</option>
              <option value="success">{t("admin.audit.success")}</option>
              <option value="denied">{t("admin.audit.denied")}</option>
              <option value="failed">{t("admin.audit.failed")}</option>
            </select>
          </span>
        }
      >
        <ResourceView resource={list} what={t("admin.what.audit_events")}>
          {(p) => (
            <>
              <AuditTable events={p.items} />
              <div className="px-5 pb-4">
                <Pager page={page} total={p.total} size={PAGE} onPage={setPage} label={t("admin.pager.audit")} />
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
  const { t, rich } = useLocale();
  const [attempt, setAttempt] = useState(0);
  const bump = () => setAttempt((n) => n + 1);
  const updates = useResource(can("population.refresh") ? `pop-upd|${attempt}` : null, "population.refresh", (s) => api.populationUpdates(s), attempt);
  const config = useResource(`pop-cfg|${attempt}`, "population.configure", (s) => api.populationConfig(s), attempt);
  const w = useWrite(bump);
  const [done, setDone] = useState(false);
  return (
    <Shell
      title={t("nav.population_aggregation")}
      subtitle={t("admin.pop.subtitle")}
      actions={
        can("population.refresh") ? (
          <button type="button" className={buttonClass("primary")} disabled={w.pending} onClick={async () => setDone(!!(await w.run(() => api.refreshPopulation())))}>
            <RefreshCw size={15} aria-hidden="true" className={w.pending ? "animate-spin" : undefined} /> {w.pending ? t("admin.pop.refreshing") : t("admin.pop.refresh")}
          </button>
        ) : undefined
      }
    >
      <FormError message={w.error} />
      {done && !w.error && <Confirmation>{t("admin.pop.refreshed")}</Confirmation>}
      <ResourceView resource={updates} what={t("admin.what.aggregation")} onRetry={bump}>
        {(u) => (
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <KpiCard
              label={t("admin.pop.status")}
              value={u.stale ? t("admin.kpi.stale") : u.aggregation_status.replace(/_/g, " ")}
              note={u.data_changed_since_aggregation ? t("admin.pop.changed") : t("admin.pop.unchanged")}
            />
            <KpiCard
              label={t("admin.pop.last_run")}
              value={u.last_aggregation_at ? formatDateTime(u.last_aggregation_at) : t("admin.pop.never")}
              size="md"
              note={u.latest_run?.trigger ? t("admin.pop.trigger", { trigger: u.latest_run.trigger.replace(/_/g, " ") }) : undefined}
            />
            <KpiCard
              label={t("admin.pop.age")}
              value={u.staleness_seconds === null ? "—" : t("admin.pop.minutes", { minutes: Math.round(u.staleness_seconds / 60) })}
            />
            <KpiCard label={t("admin.pop.complete_through")} value={u.latest_run?.complete_through ?? "—"} size="md" note={t("admin.pop.delay")} />
          </dl>
        )}
      </ResourceView>
      <Plate title={t("admin.pop.thresholds")} description={t("admin.pop.thresholds_desc")}>
        <ResourceView resource={config} what={t("admin.what.thresholds")} onRetry={bump}>
          {(c) => (
            <>
              <p className="mb-3 text-sm text-muted">
                {t(c.is_default ? "admin.pop.version_defaults" : "admin.pop.version", { version: c.version, min: c.min_cell_size })}
                {c.updated_at ? t("admin.pop.updated", { date: formatDateTime(c.updated_at) }) : ""}
              </p>
              <pre dir="ltr" className="max-h-[420px] overflow-auto rounded-lg bg-surface-sunken p-4 font-mono text-xs leading-relaxed text-foreground">
                {JSON.stringify(c.thresholds, null, 2)}
              </pre>
              <Footnote>{rich("admin.pop.footnote", { endpoint: <span className="ltr-value">`PATCH /population/config`</span> })}</Footnote>
            </>
          )}
        </ResourceView>
      </Plate>
    </Shell>
  );
}
