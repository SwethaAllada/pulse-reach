"use client";

import { homeCrumb } from "@/components/shell/nav-items";
import { useAuth } from "@/lib/auth/auth-context";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, ShieldCheck, UserX } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { LoadingState } from "@/components/ui/loading-state";
import { Surface } from "@/components/ui/surface";
import { StatusLabel } from "@/components/ui/status-glyph";
import { pathwayLabel, regionLabel } from "@/lib/population/filters";
import { listHrefFromProfile, parsePeopleState, populationHref } from "@/lib/people/params";
import {
  ageLabel,
  buildAssessment,
  buildPathways,
  buildTrace,
  gapEvidenceRefs,
  gapStatusFlags,
  historyMeta,
  programmesOf,
  sexLabel,
} from "@/lib/people/person";
import { usePersonProfile, type PersonProfileData } from "@/lib/people/use-people-data";
import { pathwayFromSlug, PROGRAMME_META } from "@/lib/programmes/model";
import { buttonClass } from "@/components/ui/button-styles";
import { BACK } from "@/components/ui/page-transition";
import { ProgrammeHistory } from "../programme-history";
import { Field, PROFILE_SECTIONS, ProfileSection, UnavailableNote } from "./profile-section";
import { AssessmentSection } from "./assessment-section";
import { EvidenceTraceSection } from "./evidence-trace";
import { CareGapsSection, PathwaySection } from "./care-gaps";
import { CoordinationSection } from "./coordination-section";
import { useLocale, useT } from "@/lib/i18n/use-locale";

/**
 * `via` = the programme or rule page the profile was opened from. Only same-origin
 * programme paths are accepted (never an arbitrary URL).
 */
function programmeVia(raw: string | null): { href: string; crumbs: { label: string; href: string }[] } | null {
  const m = /^\/programmes\/([a-z-]+)(?:\/rules\/([A-Za-z0-9._%-]+))?(\?[^#]*)?$/.exec(raw ?? "");
  const pathway = m ? pathwayFromSlug(m[1]) : null;
  if (!m || !pathway) return null;
  const programmePath = `/programmes/${m[1]}`;
  const crumbs: { label: string; href: string }[] = [{ label: PROGRAMME_META[pathway].name, href: m[2] ? programmePath : `${programmePath}${m[3] ?? ""}` }];
  if (m[2]) crumbs.push({ label: decodeURIComponent(m[2]), href: `${programmePath}/rules/${m[2]}` });
  return { href: crumbs.at(-1)!.href, crumbs };
}

export function PersonProfile() {
  const params = useParams<{ personId: string }>();
  const personId = decodeURIComponent(params.personId ?? "");
  const search = useSearchParams();
  const from = search.get("from");
  const via = programmeVia(search.get("via"));
  const listHref = listHrefFromProfile(from);
  const listFilters = parsePeopleState(new URLSearchParams(from ?? "")).filters;
  const { state, retry } = usePersonProfile(personId);
  const { role } = useAuth();
  const { t: tr, rich: richT } = useLocale();

  const breadcrumbs = via
    ? [{ label: tr("nav.programmes"), href: "/programmes" }, ...via.crumbs.map((c, i) => (i === 0 ? { ...c, label: tr(c.label as Parameters<typeof tr>[0]) } : c)), { label: personId }]
    : [
        homeCrumb(role, tr, populationHref(listFilters)),
        { label: tr("nav.people"), href: listHref },
        { label: personId },
      ];
  const back = (
    <Link href={via?.href ?? listHref} transitionTypes={BACK} className={buttonClass("secondary")}>
      <ArrowLeft size={14} aria-hidden="true" className="rtl:-scale-x-100" />{" "}
      {via
        ? tr("profile.back_to", { target: via.crumbs.length > 1 ? via.crumbs.at(-1)!.label : tr(via.crumbs[0].label as Parameters<typeof tr>[0]) })
        : tr("profile.back_people")}
    </Link>
  );

  return (
    <div className="mx-auto w-full max-w-[1280px] px-4 pb-16 pt-8 sm:px-6 lg:px-8">
      {state.status === "ready" ? (
        <ProfileBody data={state.data} breadcrumbs={breadcrumbs} back={back} />
      ) : (
        <>
          <PageHeader eyebrow={tr("profile.eyebrow")} title={personId} breadcrumbs={breadcrumbs} actions={back} className="mb-8" />
          {state.status === "loading" && (
            <div aria-busy="true" aria-label={tr("profile.loading")} className="flex flex-col gap-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="skeleton h-24 rounded-xl" style={{ animationDelay: `${i * 100}ms` }} />
                ))}
              </div>
              <LoadingState rows={6} />
            </div>
          )}
          {state.status === "not_found" && (
            <Surface className="flex flex-col items-start gap-3 p-8">
              <UserX size={24} aria-hidden="true" className="text-faint" />
              <h2 className="text-lg font-semibold text-foreground">{tr("profile.not_found")}</h2>
              <p className="text-sm text-muted">
                {richT("profile.not_found_body", { id: <span className="font-mono text-foreground">{state.id}</span> })}
              </p>
              {back}
            </Surface>
          )}
          {state.status === "error" && (
            <div role="alert" className="reveal flex flex-col items-start gap-3 rounded-xl border border-border bg-surface p-6">
              <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <AlertTriangle size={16} aria-hidden="true" className="text-status-error" />
                {tr("profile.unavailable")}
              </p>
              <p className="text-sm text-muted">{tr("profile.unavailable_body", { message: state.message })}</p>
              <button
                type="button"
                onClick={retry}
                className={buttonClass("primary")}
              >
                {tr("access.retry")}
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
  const { t, rich } = useLocale();
  const refDate = ev.reference_date;
  const programmes = programmesOf(patient);
  const assessment = useMemo(() => buildAssessment(patient, ev.evaluations, ev.care_gaps), [patient, ev]);
  const trace = useMemo(() => buildTrace(patient, ev.evaluations, ev.care_gaps), [patient, ev]);
  const pathways = useMemo(() => buildPathways(ev.care_gaps, ev.evaluations, rules, t), [ev, rules, t]);
  const openGaps = ev.care_gaps.filter((g) => gapStatusFlags(g.status).isOpen);
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
  // Deep links (e.g. `#evidence` from a programme rule) target sections that only exist once data loads.
  useEffect(() => {
    const target = window.location.hash.slice(1);
    if (target) document.getElementById(target)?.scrollIntoView({ block: "start" });
  }, []);

  const openTrace = useCallback((id: string) => {
    setExpanded((prev) => new Set(prev).add(id));
    requestAnimationFrame(() => document.getElementById(`trace-${id}`)?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, []);

  return (
    <>
      <PageHeader
        index="04"
        eyebrow={t("profile.eyebrow_synthetic")}
        title={patient.patient_id}
        subtitle={t("profile.subtitle", { run: ev.evaluation_run_id, date: refDate })}
        breadcrumbs={breadcrumbs}
        actions={back}
        className="mb-6"
      />

      <section aria-label={t("profile.glance")} className="mb-8 grid grid-cols-1 gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-4 lg:divide-x lg:divide-border rtl:lg:divide-x-reverse">
        <Glance question={t("profile.q_who")}>
          <p className="text-sm text-foreground">
            {ageLabel(patient.date_of_birth, refDate, t)} · {sexLabel(patient.sex, t)} · {regionLabel(patient.region_id, t)}
          </p>
          <p className="mt-1 text-xs text-muted">
            {programmes.length > 0 ? programmes.map((p) => pathwayLabel(p, t, true)).join(" · ") : t("people.results.no_programme")}
          </p>
        </Glance>
        <Glance question={t("profile.q_documented")}>
          {programmes.length === 0 ? (
            <p className="text-sm text-muted">{t("profile.no_history_record")}</p>
          ) : (
            programmes.map((p) => (
              <p key={p} className="text-sm text-foreground">
                {historyMeta(patient.history_by_pathway[p], t).label}
              </p>
            ))
          )}
          <p className="mt-1 text-xs text-muted">{t("profile.records_not_exposed")}</p>
        </Glance>
        <Glance question={t("profile.q_why")}>
          {openGaps.length > 0 ? (
            <StatusLabel status="due" label={t(openGaps.length === 1 ? "profile.open_gap_one" : "profile.open_gaps", { count: openGaps.length })} className="text-foreground" />
          ) : (
            <StatusLabel status="not_eligible" label={t("profile.no_open_gap")} />
          )}
          <p className="mt-1 text-xs text-muted">
            {t("profile.need_evidence", { count: trace.filter((x) => x.origin === "person_evidence").length })}
          </p>
        </Glance>
        <Glance question={t("profile.q_next")}>
          <p className="text-sm text-foreground">
            {offered.length > 0
              ? t(offered.length === 1 ? "profile.pathway_one" : "profile.pathways", { count: offered.length })
              : t("profile.no_pathway")}
          </p>
          <p className="mt-1 text-xs text-muted">
            {rich("profile.coordination_note", {
              link: (
                <a href="#coordination" className="underline-offset-4 hover:underline">
                  {t("profile.coordination_link")}
                </a>
              ),
            })}
          </p>
        </Glance>
      </section>

      <nav
        aria-label={t("profile.sections")}
        className="sticky top-16 z-20 -mx-4 mb-10 overflow-x-auto border-y border-border bg-[color-mix(in_srgb,var(--bg)_88%,transparent)] px-4 backdrop-blur-md sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8"
      >
        <ul className="flex min-w-max gap-1 py-2">
          {PROFILE_SECTIONS.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                className="inline-flex min-h-9 items-center rounded-full px-3 text-sm text-muted transition-colors hover:bg-nav-active-bg hover:text-foreground"
              >
                {t(s.label)}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex flex-col gap-12">
        <ProfileSection id="overview" title={t("profile.sec.overview")} description={t("profile.overview_desc")}>
          <Surface className="p-5">
            <dl className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
              <Field label={t("profile.f_id")}>
                <span className="font-mono ltr-value">{patient.patient_id}</span>
              </Field>
              <Field label={t("profile.f_age")}>{ageLabel(patient.date_of_birth, refDate, t)}</Field>
              <Field label={t("pop.filter.sex")}>{sexLabel(patient.sex, t)}</Field>
              <Field label={t("pop.filter.region")}>{regionLabel(patient.region_id, t)}</Field>
              <Field label={t("pop.kpi.membership")}>
                {programmes.length === 0 ? (
                  <span className="text-muted">{t("people.results.no_programme")}</span>
                ) : (
                  <span className="flex flex-col gap-1">
                    {programmes.map((p) => (
                      <ProgrammeHistory key={p} pathway={p} history={patient.history_by_pathway[p]} />
                    ))}
                  </span>
                )}
              </Field>
              <Field label={t("profile.f_evaluation")}>
                {ev.evaluation_run_id} · {refDate}
                <span className="block text-xs text-muted">{t("profile.rule_evaluations", { count: ev.evaluations.length })}</span>
              </Field>
            </dl>
            <p className="mt-5 flex gap-2 border-t border-border pt-4 text-xs text-faint">
              <ShieldCheck size={14} aria-hidden="true" className="mt-px shrink-0" />
              {t("profile.privacy_note")}
            </p>
          </Surface>
        </ProfileSection>

        <ProfileSection
          id="history"
          title={t("profile.sec.history")}
          description={t("profile.history_desc")}
        >
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {(programmes.length > 0 ? programmes : (["ifhas", "well_child"] as const)).map((p) => {
                const h = patient.history_by_pathway[p];
                return (
                  <Surface key={p} className={h === "available" ? "p-4" : "border-dashed p-4"}>
                    <ProgrammeHistory pathway={p} history={h} />
                    <p className="mt-2 text-sm text-muted">{historyMeta(h, t).description}</p>
                  </Surface>
                );
              })}
            </div>
            <HistoricalRecords data={data} />
            <UnavailableNote title={t("profile.records_unavailable")}>{t("profile.records_unavailable_body")}</UnavailableNote>
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

        <CoordinationSection data={data} />
      </div>
    </>
  );
}

function Glance({ question, children }: { question: string; children: React.ReactNode }) {
  return (
    <div className="reveal min-w-0 lg:px-6 lg:first:ps-0">
      <h2 className="mb-2 text-xs font-medium text-warm-text">{question}</h2>
      {children}
    </div>
  );
}

function HistoricalRecords({ data }: { data: PersonProfileData }) {
  const t = useT();
  const refs = data.evaluations.care_gaps.flatMap((g) =>
    gapEvidenceRefs(g, t).map((r) => ({ ...r, ruleId: g.rule_id, key: `${g.care_gap_id}-${r.id}` }))
  );
  if (refs.length === 0) return null;
  return (
    <Surface className="p-4">
      <h3 className="text-sm font-semibold text-foreground">{t("profile.refs_title")}</h3>
      <p className="mt-0.5 text-xs text-muted">{t("profile.refs_note")}</p>
      <ul className="mt-3 flex flex-col divide-y divide-border">
        {refs.map((r) => (
          <li key={r.key} className="flex flex-wrap items-baseline justify-between gap-2 py-2 text-sm">
            <span className="text-foreground">{r.label}</span>
            <span className="font-mono text-xs text-muted ltr-value">
              {r.id} · {r.ruleId}
            </span>
          </li>
        ))}
      </ul>
    </Surface>
  );
}
