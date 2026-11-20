"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Plus, ShieldCheck } from "lucide-react";
import type { Resource } from "@/lib/api/resource";
import { useAuth } from "@/lib/auth/auth-context";
import { TERMINAL_TASK_STATUSES, buildTimeline, formatDate, formatDateTime, isoDate, type TimelineKind } from "@/lib/coordination/model";
import { useCareTeam, usePatientCoordination, useRulesIndex } from "@/lib/coordination/use-coordination";
import type { PersonProfileData } from "@/lib/people/use-people-data";
import { buttonClass } from "@/components/ui/button-styles";
import { Segmented } from "@/components/ui/segmented";
import { LoadingState } from "@/components/ui/loading-state";
import { InlineError } from "@/components/programmes/resource-state";
import { CreateTaskForm } from "@/components/coordination/create-task-form";
import { TaskList } from "@/components/coordination/follow-up-workspace";
import { Confirmation, QuietEmpty, ToneGlyph, VisibilityBadge } from "@/components/coordination/primitives";
import { ProfileSection } from "./profile-section";

type Lane = "all" | "follow_up" | "outreach" | "appointments" | "referrals" | "requests";

const LANES: Record<Lane, TimelineKind[] | null> = {
  all: null,
  follow_up: ["task", "note", "gap", "completion"],
  outreach: ["outreach"],
  appointments: ["appointment"],
  referrals: ["referral"],
  requests: ["request"],
};

function ready<T>(r: Resource<T>): T | null {
  return r.status === "ready" ? r.data : null;
}

/**
 * Everything coordinated for this person — follow-ups, outreach reviews, requests, appointments,
 * referrals — as one dated timeline. Each part loads under its own permission; a refused part is
 * named, never silently dropped.
 */
export function CoordinationSection({ data }: { data: PersonProfileData }) {
  const { can } = useAuth();
  const pid = data.patient.patient_id;
  const [attempt, setAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<string | null>(null);
  const [lane, setLane] = useState<Lane>("all");
  const c = usePatientCoordination(pid, attempt);
  const team = useCareTeam(pid);
  const rules = useRulesIndex();
  const today = useMemo(() => isoDate(new Date()), []);
  const now = useMemo(() => new Date().toISOString(), []);

  const tasks = ready(c.tasks);
  const activity = ready(c.activity);
  const parts = [c.tasks, c.activity, c.requests, c.appointments, c.referrals];
  const loading = parts.some((p) => p.status === "loading");
  const errors = parts.filter((p): p is { status: "error"; message: string } => p.status === "error");
  const refused = [
    c.requests.status === "forbidden" && "patient requests",
    c.appointments.status === "forbidden" && "appointments",
    c.referrals.status === "forbidden" && "referrals",
    c.tasks.status === "forbidden" && "follow-ups",
  ].filter(Boolean) as string[];

  const timeline = useMemo(
    () =>
      buildTimeline({
        careGaps: data.evaluations.care_gaps,
        tasks: tasks ?? [],
        followUps: activity?.follow_up_events ?? [],
        workflow: activity?.workflow_events ?? [],
        requests: ready(c.requests) ?? [],
        appointments: ready(c.appointments) ?? [],
        referrals: ready(c.referrals) ?? [],
        team: ready(team),
      }),
    [data, tasks, activity, c.requests, c.appointments, c.referrals, team]
  );
  const shown = LANES[lane] ? timeline.filter((e) => LANES[lane]!.includes(e.kind)) : timeline;
  const activeTasks = tasks?.filter((t) => !TERMINAL_TASK_STATUSES.includes(t.status)) ?? null;
  const upcoming = ready(c.appointments)?.filter((a) => (a.status === "scheduled" || a.status === "rescheduled") && a.scheduled_datetime >= now) ?? null;
  const openRequests = ready(c.requests)?.filter((r) => r.status === "submitted" || r.status === "acknowledged") ?? null;
  const activeReferrals = ready(c.referrals)?.filter((r) => r.status === "pending" || r.status === "initiated") ?? null;

  return (
    <ProfileSection
      id="coordination"
      title="Care Coordination"
      description="Follow-ups, outreach reviews, patient requests, appointments and referrals for this person. Only a documented completion with evidence closes a care gap."
    >
      <div className="flex flex-col gap-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <dl className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
            <Count label="Active follow-ups" value={activeTasks?.length} />
            <Count label="Open requests" value={openRequests?.length} />
            <Count label="Upcoming appointments" value={upcoming?.length} />
            <Count label="Active referrals" value={activeReferrals?.length} />
          </dl>
          {can("followups.create") && !creating && (
            <button type="button" className={buttonClass("primary")} onClick={() => { setCreating(true); setCreated(null); }}>
              <Plus size={15} aria-hidden="true" /> New follow-up
            </button>
          )}
        </div>

        {creating && (
          <CreateTaskForm
            patientId={pid}
            gaps={data.evaluations.care_gaps}
            today={today}
            onCancel={() => setCreating(false)}
            onCreated={(t) => {
              setCreating(false);
              setCreated(t.task_id);
            }}
          />
        )}
        {created && (
          <Confirmation>
            Follow-up created.{" "}
            <Link className="font-medium text-accent underline-offset-4 hover:underline" href={`/follow-up/${encodeURIComponent(created)}`}>
              Open it
            </Link>
          </Confirmation>
        )}

        {errors.length > 0 && <InlineError message={`Some coordination records are unavailable. ${errors[0].message}`} onRetry={() => setAttempt((n) => n + 1)} />}
        {refused.length > 0 && (
          <p className="text-xs text-faint">Not shown for your role: {refused.join(", ")} (enforced by the PulseReach API).</p>
        )}

        {tasks && tasks.length > 0 && (
          <div>
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-faint">Follow-ups</h3>
            <TaskList tasks={tasks} team={ready(team)} rules={ready(rules)} today={today} hidePatient />
          </div>
        )}

        <div>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-faint">Timeline</h3>
            <div className="overflow-x-auto">
              <Segmented
                label="Timeline lane"
                value={lane}
                onChange={setLane}
                className="min-w-max"
                options={[
                  { value: "all", label: "All" },
                  { value: "follow_up", label: "Follow-up" },
                  { value: "outreach", label: "Outreach" },
                  { value: "requests", label: "Requests" },
                  { value: "appointments", label: "Appointments" },
                  { value: "referrals", label: "Referrals" },
                ]}
              />
            </div>
          </div>
          {loading ? (
            <LoadingState rows={4} label="Loading coordination timeline" />
          ) : shown.length === 0 ? (
            <QuietEmpty title="Nothing recorded yet">No coordination activity is recorded for this lane.</QuietEmpty>
          ) : (
            <ol aria-label="Coordination timeline" className="relative flex flex-col gap-4 border-l border-border pl-5">
              {shown.map((e, i) => (
                <li key={e.id} className="reveal relative" style={{ "--i": Math.min(i, 10) } as React.CSSProperties}>
                  <span className="absolute -left-[27px] top-1 rounded-full bg-background p-0.5">
                    <ToneGlyph tone={e.tone} />
                  </span>
                  <div className="flex flex-wrap items-center gap-2">
                    {e.href ? (
                      <Link href={e.href} className="text-sm font-medium text-foreground underline-offset-4 hover:underline">
                        {e.title}
                      </Link>
                    ) : (
                      <span className="text-sm font-medium text-foreground">{e.title}</span>
                    )}
                    <VisibilityBadge visibility={e.visibility} />
                  </div>
                  {e.detail && <p className="mt-0.5 whitespace-pre-wrap text-sm text-muted">{e.detail}</p>}
                  <p className="mt-0.5 text-xs text-faint">{e.at.length === 10 ? formatDate(e.at) : formatDateTime(e.at)}</p>
                </li>
              ))}
            </ol>
          )}
        </div>

        <p className="flex gap-2 border-t border-border pt-4 text-xs text-faint">
          <ShieldCheck size={14} aria-hidden="true" className="mt-px shrink-0" />
          Internal entries are staff-only and never appear in the patient portal. Appointments, referrals, patient replies and approved (simulated) outreach are
          coordination records, not proof that preventive care was completed.
        </p>
      </div>
    </ProfileSection>
  );
}

function Count({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-[0.08em] text-faint">{label}</dt>
      <dd className="figure mt-1 text-2xl text-foreground">{value ?? "—"}</dd>
    </div>
  );
}
