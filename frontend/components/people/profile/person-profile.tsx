"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, ShieldCheck, UserX } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { LoadingState } from "@/components/ui/loading-state";
import { Surface } from "@/components/ui/surface";
import { StatusLabel } from "@/components/ui/status-glyph";
import { regionLabel } from "@/lib/population/filters";
import { listHrefFromProfile, parsePeopleState, populationHref } from "@/lib/people/params";
import {
  ageLabel,
  buildAssessment,
  buildPathways,
  buildTrace,
  gapEvidenceRefs,
  gapStatusMeta,
  historyMeta,
  programmesOf,
  sexLabel,
} from "@/lib/people/person";
import { usePersonProfile, type PersonProfileData } from "@/lib/people/use-people-data";
import { ProgrammeHistory } from "../programme-history";
import { Field, PROFILE_SECTIONS, ProfileSection, UnavailableNote } from "./profile-section";
import { AssessmentSection } from "./assessment-section";
import { EvidenceTraceSection } from "./evidence-trace";
import { CareGapsSection, PathwaySection } from "./care-gaps";

export function PersonProfile() {
  const params = useParams<{ personId: string }>();
  const personId = decodeURIComponent(params.personId ?? "");
  const from = useSearchParams().get("from");
  const listHref = listHrefFromProfile(from);
  const listFilters = parsePeopleState(new URLSearchParams(from ?? "")).filters;
  const { state, retry } = usePersonProfile(personId);

  const breadcrumbs = [
    { label: "Population", href: populationHref(listFilters) },
    { label: "People", href: listHref },
    { label: personId },
  ];
  const back = (
    <Link
      href={listHref}
      className="inline-flex items-center gap-1.5 rounded-md border border-border-strong px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:border-accent"
    >
      <ArrowLeft size={14} aria-hidden="true" /> Back to People
    </Link>
  );

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-8">
      {state.status === "ready" ? (
        <ProfileBody data={state.data} breadcrumbs={breadcrumbs} back={back} />
      ) : (
        <>
          <PageHeader eyebrow="Person profile" title={personId} breadcrumbs={breadcrumbs} actions={back} className="mb-8" />
          {state.status === "loading" && (
            <div aria-busy="true" aria-label="Loading person profile" className="flex flex-col gap-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="h-28 animate-pulse rounded-lg bg-surface-sunken" />
                ))}
              </div>
              <LoadingState rows={6} />
            </div>
          )}
          {state.status === "not_found" && (
            <Surface className="flex flex-col items-start gap-3 p-8">
              <UserX size={24} aria-hidden="true" className="text-faint" />
              <h2 className="text-lg font-semibold text-foreground">Person not found</h2>
              <p className="text-sm text-muted">
                There is no synthetic person with ID <span className="font-mono text-foreground">{state.id}</span> in this
                dataset. Check the ID or return to the People list.
              </p>
              {back}
            </Surface>
          )}
          {state.status === "error" && (
            <div role="alert" className="flex flex-col items-start gap-3 rounded-lg border border-border bg-surface p-6">
              <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <AlertTriangle size={16} aria-hidden="true" className="text-status-error" />
                This profile is unavailable
              </p>
              <p className="text-sm text-muted">{state.message} No profile information is shown in place of API data.</p>
              <button
                type="button"
                onClick={retry}
                className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-on-accent transition-opacity hover:opacity-90"
              >
                Retry
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ProfileBody({
  data,
  breadcrumbs,
  back,
}: {
  data: PersonProfileData;
  breadcrumbs: { label: string; href?: string }[];
  back: React.ReactNode;
}) {
  const { patient, evaluations: ev, rules } = data;
  const refDate = ev.reference_date;
  const programmes = programmesOf(patient);
  const assessment = useMemo(() => buildAssessment(patient, ev.evaluations, ev.care_gaps), [patient, ev]);
  const trace = useMemo(() => buildTrace(patient, ev.evaluations, ev.care_gaps), [patient, ev]);
  const pathways = useMemo(() => buildPathways(ev.care_gaps, ev.evaluations, rules), [ev, rules]);
  const openGaps = ev.care_gaps.filter((g) => gapStatusMeta(g.status).isOpen);
  const offered = pathways.filter((p) => p.offered);

  const firstGapTrace = trace.find((t) => t.origin === "care_gap")?.evaluation.evaluation_id;
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(firstGapTrace ? [firstGapTrace] : []));
  const toggle = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);
  const openTrace = useCallback((id: string) => {
    setExpanded((prev) => new Set(prev).add(id));
    requestAnimationFrame(() => document.getElementById(`trace-${id}`)?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, []);

  return (
    <>
      <PageHeader
        eyebrow="Person profile · synthetic record"
        title={patient.patient_id}
        subtitle={`Evaluation run ${ev.evaluation_run_id} · reference date ${refDate}. Every value below comes from the PulseReach API and its configured rules.`}
        breadcrumbs={breadcrumbs}
        actions={back}
        className="mb-6"
      />

      <section aria-label="At a glance" className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Glance question="Who is this person?">
          <p className="text-sm text-foreground">
            {ageLabel(patient.date_of_birth, refDate)} · {sexLabel(patient.sex)} · {regionLabel(patient.region_id)}
          </p>
          <p className="mt-1 text-xs text-muted">
            {programmes.length > 0 ? programmes.map((p) => (p === "ifhas" ? "IFHAS" : "Well-Child")).join(" · ") : "No programme history record"}
          </p>
        </Glance>
        <Glance question="What is documented?">
          {programmes.length === 0 ? (
            <p className="text-sm text-muted">No history-availability record.</p>
          ) : (
            programmes.map((p) => (
              <p key={p} className="text-sm text-foreground">
                {historyMeta(patient.history_by_pathway[p]).label}
              </p>
            ))
          )}
          <p className="mt-1 text-xs text-muted">Screening record details are not exposed by the API.</p>
        </Glance>
        <Glance question="Why identified?">
          {openGaps.length > 0 ? (
            <StatusLabel status="due" label={`${openGaps.length} open documented ${openGaps.length === 1 ? "gap" : "gaps"}`} className="text-foreground" />
          ) : (
            <StatusLabel status="not_eligible" label="No open documented gap" />
          )}
          <p className="mt-1 text-xs text-muted">
            {trace.filter((t) => t.origin === "person_evidence").length} results need missing or conflicting evidence.
          </p>
        </Glance>
        <Glance question="Supported next step">
          <p className="text-sm text-foreground">
            {offered.length > 0
              ? `${offered.length} supported ${offered.length === 1 ? "pathway" : "pathways"}`
              : "No supported pathway"}
          </p>
          <p className="mt-1 text-xs text-muted">Outreach and referrals are not available in this phase.</p>
        </Glance>
      </section>

      <nav
        aria-label="Profile sections"
        className="sticky top-16 z-20 -mx-4 mb-8 overflow-x-auto border-y border-border bg-background/95 px-4 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8"
      >
        <ul className="flex min-w-max gap-1 py-2">
          {PROFILE_SECTIONS.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                className="inline-flex min-h-9 items-center rounded-md px-3 text-sm text-muted transition-colors hover:bg-nav-active-bg hover:text-foreground"
              >
                {s.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex flex-col gap-12">
        <ProfileSection id="overview" title="Overview" description="Fields returned for this synthetic person. Missing values are shown as missing, never as a negative result.">
          <Surface className="p-5">
            <dl className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Synthetic person ID">
                <span className="font-mono">{patient.patient_id}</span>
              </Field>
              <Field label="Age at reference date">{ageLabel(patient.date_of_birth, refDate)}</Field>
              <Field label="Sex">{sexLabel(patient.sex)}</Field>
              <Field label="Region">{regionLabel(patient.region_id)}</Field>
              <Field label="Programme membership">
                {programmes.length === 0 ? (
                  <span className="text-muted">No programme history record</span>
                ) : (
                  <span className="flex flex-col gap-1">
                    {programmes.map((p) => (
                      <ProgrammeHistory key={p} pathway={p} history={patient.history_by_pathway[p]} />
                    ))}
                  </span>
                )}
              </Field>
              <Field label="Evaluation">
                {ev.evaluation_run_id} · {refDate}
                <span className="block text-xs text-muted">{ev.evaluations.length} rule evaluations</span>
              </Field>
            </dl>
            <p className="mt-5 flex gap-2 border-t border-border pt-4 text-xs text-faint">
              <ShieldCheck size={14} aria-hidden="true" className="mt-px shrink-0" />
              Names, synthetic Emirates IDs and contact details exist on the synthetic record but are intentionally not
              displayed. Programme membership is the presence of a history record for that programme.
            </p>
          </Surface>
        </ProfileSection>

        <ProfileSection
          id="history"
          title="Screening & History"
          description="Historical evidence available to the engine. This is separate from the current evaluation results below."
        >
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {(programmes.length > 0 ? programmes : (["ifhas", "well_child"] as const)).map((p) => {
                const h = patient.history_by_pathway[p];
                return (
                  <Surface key={p} className={h === "available" ? "p-4" : "border-dashed p-4"}>
                    <ProgrammeHistory pathway={p} history={h} />
                    <p className="mt-2 text-sm text-muted">{historyMeta(h).description}</p>
                  </Surface>
                );
              })}
            </div>
            <HistoricalRecords data={data} />
            <UnavailableNote title="Screening and visit records are not available from the API">
              Dates, completion statuses and sources of individual screenings, visits and assessments are not returned
              (no patient history endpoint; evaluations omit the last completed date). Their absence here is not evidence
              that no screening took place.
            </UnavailableNote>
          </div>
        </ProfileSection>

        <AssessmentSection assessment={assessment} openGaps={openGaps.length} />

        <EvidenceTraceSection
          data={data}
          items={trace}
          expanded={expanded}
          onToggle={toggle}
        />

        <CareGapsSection data={data} pathways={pathways} onTrace={openTrace} />

        <PathwaySection data={data} pathways={pathways} trace={trace} />
      </div>
    </>
  );
}

function Glance({ question, children }: { question: string; children: React.ReactNode }) {
  return (
    <Surface className="p-4">
      <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">{question}</h2>
      {children}
    </Surface>
  );
}

function HistoricalRecords({ data }: { data: PersonProfileData }) {
  const refs = data.evaluations.care_gaps.flatMap((g) =>
    gapEvidenceRefs(g).map((r) => ({ ...r, ruleId: g.rule_id, key: `${g.care_gap_id}-${r.id}` }))
  );
  if (refs.length === 0) return null;
  return (
    <Surface className="p-4">
      <h3 className="text-sm font-semibold text-foreground">Documented records referenced by care gaps</h3>
      <p className="mt-0.5 text-xs text-muted">Only the record IDs are returned; their contents are not exposed.</p>
      <ul className="mt-3 flex flex-col divide-y divide-border">
        {refs.map((r) => (
          <li key={r.key} className="flex flex-wrap items-baseline justify-between gap-2 py-2 text-sm">
            <span className="text-foreground">{r.label}</span>
            <span className="font-mono text-xs text-muted">
              {r.id} · {r.ruleId}
            </span>
          </li>
        ))}
      </ul>
    </Surface>
  );
}
