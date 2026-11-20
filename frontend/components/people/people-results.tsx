"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, ChevronLeft, ChevronRight, SearchX, UserX } from "lucide-react";
import type { PatientSummaryOut } from "@/lib/api/types";
import type { LoadState } from "@/lib/population/use-population-data";
import { regionLabel } from "@/lib/population/filters";
import { PAGE_SIZE, hasAnyCriteria, profileHref, type PeopleState } from "@/lib/people/params";
import { ageLabel, programmesOf, sexLabel } from "@/lib/people/person";
import type { PeoplePage, PeopleReference } from "@/lib/people/use-people-data";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusGlyph } from "@/components/ui/status-glyph";
import { ProgrammeHistory } from "./programme-history";
import { buttonClass } from "@/components/ui/button-styles";
import { useLocale } from "@/lib/i18n/use-locale";

interface Props {
  state: PeopleState;
  page: LoadState<PeoplePage>;
  reference: LoadState<PeopleReference>;
  onRetry: () => void;
  onNavigate: (next: PeopleState) => void;
}

export function PeopleResults({ state, page, reference, onRetry, onNavigate }: Props) {
  const { t } = useLocale();
  if (page.status === "loading") return <ResultsSkeleton />;
  if (page.status === "error")
    return (
      <div role="alert" className="reveal flex flex-col items-start gap-3 rounded-xl border border-border bg-surface p-6">
        <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <AlertTriangle size={16} aria-hidden="true" className="text-status-error" />
          {t("people.results.unavailable")}
        </p>
        <p className="text-sm text-muted">{t("people.results.unavailable_body", { message: page.message })}</p>
        <button
          type="button"
          onClick={onRetry}
          className={buttonClass("primary")}
        >
          {t("access.retry")}
        </button>
      </div>
    );

  const { rows, total, mode, excludedByFilters } = page.data;
  const ref = reference.status === "ready" ? reference.data : null;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  if (rows.length === 0) {
    if (mode === "id" && excludedByFilters)
      return (
        <EmptyStateWithAction
          title={t("people.results.excluded_title", { id: excludedByFilters.patient_id })}
          description={t("people.results.excluded_desc")}
          action={t("people.results.excluded_action")}
          onAction={() => onNavigate({ filters: {}, page: 1, id: state.id })}
        />
      );
    if (mode === "id")
      return (
        <EmptyStateWithAction
          icon={UserX}
          title={t("people.results.no_id_title", { id: state.id ?? "" })}
          description={t("people.results.no_id_desc")}
          action={t("people.search.clear")}
          onAction={() => onNavigate({ ...state, id: null, page: 1 })}
        />
      );
    if (total > 0 && state.page > lastPage)
      return (
        <EmptyStateWithAction
          title={t("people.results.past_title", { page: state.page })}
          description={t("people.results.past_desc", { total, last: lastPage })}
          action={t("people.results.past_action", { last: lastPage })}
          onAction={() => onNavigate({ ...state, page: lastPage })}
        />
      );
    return hasAnyCriteria(state) ? (
      <EmptyStateWithAction
        title={t("pop.empty_title")}
        description={t("pop.empty_filtered")}
        action={t("pop.clear_all_filters")}
        onAction={() => onNavigate({ filters: {}, page: 1, id: null })}
      />
    ) : (
      <EmptyState icon={SearchX} title={t("people.results.none_title")} description={t("pop.empty_all")} />
    );
  }

  const gapCell = (p: PatientSummaryOut) => {
    if (reference.status === "loading") return <span className="skeleton inline-block h-4 w-8 rounded" aria-label={t("state.loading")} />;
    if (!ref) return <span className="text-faint">{t("people.results.cell_unavailable")}</span>;
    const n = ref.openGaps.get(p.patient_id) ?? 0;
    return n > 0 ? (
      <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
        <StatusGlyph status="due" /> <span className="tabular-nums">{n}</span>
        <span className="sr-only">{t(n === 1 ? "people.results.gap_sr_one" : "people.results.gap_sr")}</span>
      </span>
    ) : (
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-muted">
        <StatusGlyph status="not_eligible" /> {t("people.results.none_documented")}
      </span>
    );
  };
  const age = (p: PatientSummaryOut) =>
    ref ? ageLabel(p.date_of_birth, ref.referenceDate, t) : p.date_of_birth ? "…" : t("pop.sex.not_recorded");

  return (
    <section aria-label={t("people.results.label")}>
      {reference.status === "error" && (
        <p role="status" className="mb-3 rounded-xl bg-surface-sunken px-3 py-2 text-xs text-muted">
          {t("people.results.ref_unavailable", { message: reference.message })}
        </p>
      )}

      <div className="reveal hidden overflow-hidden rounded-xl border border-border bg-surface md:block">
        <table className="w-full table-fixed text-start text-sm">
          <caption className="sr-only">
            {mode === "id" ? t("people.results.caption_id") : t("people.results.caption_page", { page: state.page, last: lastPage })}
          </caption>
          <thead className="border-b border-border-strong text-[11px] uppercase tracking-[0.12em] text-faint">
            <tr>
              <th scope="col" className="w-[22%] px-4 py-2.5 text-start font-medium">{t("people.col.person")}</th>
              <th scope="col" className="w-[13%] px-4 py-2.5 text-start font-medium">{t("people.col.age")}</th>
              <th scope="col" className="w-[10%] px-4 py-2.5 text-start font-medium">{t("pop.filter.sex")}</th>
              <th scope="col" className="w-[13%] px-4 py-2.5 text-start font-medium">{t("pop.filter.region")}</th>
              <th scope="col" className="px-4 py-2.5 text-start font-medium">{t("people.col.programme")}</th>
              <th scope="col" className="w-[17%] px-4 py-2.5 text-start font-medium">{t("people.col.gaps")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((p) => (
              <PersonRow key={p.patient_id} person={p} href={profileHref(p.patient_id, state)} age={age(p)} gaps={gapCell(p)} />
            ))}
          </tbody>
        </table>
      </div>

      <ul className="flex flex-col gap-3 md:hidden" aria-label={t("nav.people")}>
        {rows.map((p) => (
          <li key={p.patient_id}>
            <Link
              href={profileHref(p.patient_id, state)}
              className="block rounded-xl border border-border bg-surface p-4 transition-colors hover:border-accent"
            >
              <span className="flex items-center justify-between gap-2">
                <span className="font-mono text-sm font-semibold text-foreground"><span className="ltr-value">{p.patient_id}</span></span>
                <ChevronRight size={16} aria-hidden="true" className="text-faint rtl:-scale-x-100" />
              </span>
              <span className="mt-1 block text-xs text-muted">
                {age(p)} · {sexLabel(p.sex, t)} · {regionLabel(p.region_id, t)}
              </span>
              <span className="mt-2 flex flex-col gap-1">
                {programmesOf(p).map((pw) => (
                  <ProgrammeHistory key={pw} pathway={pw} history={p.history_by_pathway[pw]} compact />
                ))}
                {programmesOf(p).length === 0 && <span className="text-xs text-faint">{t("people.results.no_programme")}</span>}
              </span>
              <span className="mt-2 flex items-center gap-2 border-t border-border pt-2 text-xs">
                <span className="text-faint">{t("people.col.gaps")}</span>
                {gapCell(p)}
              </span>
            </Link>
          </li>
        ))}
      </ul>

      {mode === "list" && (
        <Pagination
          page={state.page}
          lastPage={lastPage}
          total={total}
          shown={rows.length}
          onPage={(n) => {
            onNavigate({ ...state, page: n });
            document.getElementById("main-content")?.scrollIntoView({ block: "start" });
          }}
        />
      )}
    </section>
  );
}

function PersonRow({ person: p, href, age, gaps }: { person: PatientSummaryOut; href: string; age: string; gaps: React.ReactNode }) {
  const router = useRouter();
  const { t } = useLocale();
  const programmes = programmesOf(p);
  return (
    <tr
      onClick={(e) => {
        if (!(e.target as HTMLElement).closest("a")) router.push(href);
      }}
      className="reveal-fade cursor-pointer align-top transition-colors duration-150 hover:bg-highlight/60 focus-within:bg-highlight/60"
    >
      <td className="px-4 py-3">
        <Link href={href} className="font-mono text-[13px] font-semibold text-foreground underline-offset-4 hover:text-accent hover:underline">
          <span className="ltr-value">{p.patient_id}</span>
        </Link>
      </td>
      <td className="px-4 py-3 text-muted">{age}</td>
      <td className="px-4 py-3 text-muted">{sexLabel(p.sex, t)}</td>
      <td className="px-4 py-3 text-muted">{regionLabel(p.region_id, t)}</td>
      <td className="px-4 py-3">
        <span className="flex flex-col gap-1">
          {programmes.map((pw) => (
            <ProgrammeHistory key={pw} pathway={pw} history={p.history_by_pathway[pw]} compact />
          ))}
          {programmes.length === 0 && <span className="text-xs text-faint">{t("people.results.no_programme")}</span>}
        </span>
      </td>
      <td className="px-4 py-3">{gaps}</td>
    </tr>
  );
}

function Pagination({
  page,
  lastPage,
  total,
  shown,
  onPage,
}: {
  page: number;
  lastPage: number;
  total: number;
  shown: number;
  onPage: (n: number) => void;
}) {
  const start = (page - 1) * PAGE_SIZE + 1;
  const btn = buttonClass("secondary");
  const { t, rich } = useLocale();
  return (
    <nav aria-label={t("people.page.label")} className="mt-4 flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-muted">
        {rich("people.page.showing", {
          range: <span className="tabular-nums text-foreground ltr-value">{start}–{start + shown - 1}</span>,
          total: <span className="tabular-nums text-foreground">{total}</span>,
        })}
      </p>
      <div className="flex items-center gap-2">
        <button type="button" className={btn} disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft size={14} aria-hidden="true" className="rtl:-scale-x-100" /> {t("people.page.previous")}
        </button>
        <span className="px-1 text-sm tabular-nums text-muted" aria-current="page">
          {t("people.page.of", { page, last: lastPage })}
        </span>
        <button type="button" className={btn} disabled={page >= lastPage} onClick={() => onPage(page + 1)}>
          {t("people.page.next")} <ChevronRight size={14} aria-hidden="true" className="rtl:-scale-x-100" />
        </button>
      </div>
    </nav>
  );
}

function EmptyStateWithAction({
  icon = SearchX,
  title,
  description,
  action,
  onAction,
}: {
  icon?: typeof SearchX;
  title: string;
  description: string;
  action: string;
  onAction: () => void;
}) {
  return (
    <div className="flex flex-col items-center gap-4">
      <div className="w-full">
        <EmptyState icon={icon} title={title} description={description} />
      </div>
      <button
        type="button"
        onClick={onAction}
        className={buttonClass("primary")}
      >
        {action}
      </button>
    </div>
  );
}

function ResultsSkeleton() {
  const { t } = useLocale();
  return (
    <div aria-busy="true" aria-label={t("people.results.loading")} className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="h-9 border-b border-border-strong" />
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex items-center gap-6 border-b border-border px-4 py-3.5 last:border-0">
          <div className="skeleton h-4 w-36 rounded" style={{ animationDelay: `${i * 80}ms` }} />
          <div className="skeleton h-4 w-16 rounded" />
          <div className="skeleton hidden h-4 w-14 rounded sm:block" />
          <div className="skeleton hidden h-4 w-40 rounded md:block" />
        </div>
      ))}
    </div>
  );
}
