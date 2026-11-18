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

interface Props {
  state: PeopleState;
  page: LoadState<PeoplePage>;
  reference: LoadState<PeopleReference>;
  onRetry: () => void;
  onNavigate: (next: PeopleState) => void;
}

export function PeopleResults({ state, page, reference, onRetry, onNavigate }: Props) {
  if (page.status === "loading") return <ResultsSkeleton />;
  if (page.status === "error")
    return (
      <div role="alert" className="flex flex-col items-start gap-3 rounded-lg border border-border bg-surface p-6">
        <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <AlertTriangle size={16} aria-hidden="true" className="text-status-error" />
          People are unavailable
        </p>
        <p className="text-sm text-muted">{page.message} No people are shown in place of API data.</p>
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-on-accent transition-opacity hover:opacity-90"
        >
          Retry
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
          title={`${excludedByFilters.patient_id} does not match the active filters`}
          description="This synthetic person exists, but the programme, region or sex filters exclude them."
          action="Clear filters and show this person"
          onAction={() => onNavigate({ filters: {}, page: 1, id: state.id })}
        />
      );
    if (mode === "id")
      return (
        <EmptyStateWithAction
          icon={UserX}
          title={`No synthetic person with ID ${state.id}`}
          description="The patients API has no record with this exact ID. Partial or name matches are not supported."
          action="Clear ID search"
          onAction={() => onNavigate({ ...state, id: null, page: 1 })}
        />
      );
    if (total > 0 && state.page > lastPage)
      return (
        <EmptyStateWithAction
          title={`Page ${state.page} is past the last page`}
          description={`${total} people match; the last page is ${lastPage}.`}
          action={`Go to page ${lastPage}`}
          onAction={() => onNavigate({ ...state, page: lastPage })}
        />
      );
    return hasAnyCriteria(state) ? (
      <EmptyStateWithAction
        title="No people match these filters"
        description="The patients API returned no synthetic people for this combination."
        action="Clear all filters"
        onAction={() => onNavigate({ filters: {}, page: 1, id: null })}
      />
    ) : (
      <EmptyState icon={SearchX} title="No people returned" description="The patients API returned an empty population." />
    );
  }

  const gapCell = (p: PatientSummaryOut) => {
    if (reference.status === "loading") return <span className="inline-block h-4 w-8 animate-pulse rounded bg-surface-sunken" aria-label="Loading" />;
    if (!ref) return <span className="text-faint">Unavailable</span>;
    const n = ref.openGaps.get(p.patient_id) ?? 0;
    return n > 0 ? (
      <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
        <StatusGlyph status="due" /> <span className="tabular-nums">{n}</span>
        <span className="sr-only">open documented {n === 1 ? "gap" : "gaps"}</span>
      </span>
    ) : (
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-muted">
        <StatusGlyph status="not_eligible" /> None documented
      </span>
    );
  };
  const age = (p: PatientSummaryOut) => (ref ? ageLabel(p.date_of_birth, ref.referenceDate) : p.date_of_birth ? "…" : "Not recorded");

  return (
    <section aria-label="People results">
      {reference.status === "error" && (
        <p role="status" className="mb-3 rounded-md border border-border bg-surface-sunken px-3 py-2 text-xs text-muted">
          Open-gap counts and ages are unavailable: {reference.message}
        </p>
      )}

      <div className="hidden overflow-hidden rounded-lg border border-border bg-surface shadow-[var(--shadow-card)] md:block">
        <table className="w-full table-fixed text-left text-sm">
          <caption className="sr-only">
            Synthetic people, {mode === "id" ? "exact ID match" : `page ${state.page} of ${lastPage}`}
          </caption>
          <thead className="border-b border-border bg-surface-sunken text-[11px] uppercase tracking-[0.08em] text-faint">
            <tr>
              <th scope="col" className="w-[22%] px-4 py-2.5 font-medium">Person</th>
              <th scope="col" className="w-[13%] px-4 py-2.5 font-medium">Age</th>
              <th scope="col" className="w-[10%] px-4 py-2.5 font-medium">Sex</th>
              <th scope="col" className="w-[13%] px-4 py-2.5 font-medium">Region</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Programme · history</th>
              <th scope="col" className="w-[17%] px-4 py-2.5 font-medium">Open documented gaps</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((p) => (
              <PersonRow key={p.patient_id} person={p} href={profileHref(p.patient_id, state)} age={age(p)} gaps={gapCell(p)} />
            ))}
          </tbody>
        </table>
      </div>

      <ul className="flex flex-col gap-3 md:hidden" aria-label="People">
        {rows.map((p) => (
          <li key={p.patient_id}>
            <Link
              href={profileHref(p.patient_id, state)}
              className="block rounded-lg border border-border bg-surface p-4 shadow-[var(--shadow-card)] transition-colors hover:border-accent"
            >
              <span className="flex items-center justify-between gap-2">
                <span className="font-mono text-sm font-semibold text-foreground">{p.patient_id}</span>
                <ChevronRight size={16} aria-hidden="true" className="text-faint" />
              </span>
              <span className="mt-1 block text-xs text-muted">
                {age(p)} · {sexLabel(p.sex)} · {regionLabel(p.region_id)}
              </span>
              <span className="mt-2 flex flex-col gap-1">
                {programmesOf(p).map((pw) => (
                  <ProgrammeHistory key={pw} pathway={pw} history={p.history_by_pathway[pw]} compact />
                ))}
                {programmesOf(p).length === 0 && <span className="text-xs text-faint">No programme history record</span>}
              </span>
              <span className="mt-2 flex items-center gap-2 border-t border-border pt-2 text-xs">
                <span className="text-faint">Open documented gaps</span>
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
  const programmes = programmesOf(p);
  return (
    <tr
      onClick={(e) => {
        if (!(e.target as HTMLElement).closest("a")) router.push(href);
      }}
      className="cursor-pointer align-top transition-colors hover:bg-accent-soft focus-within:bg-accent-soft"
    >
      <td className="px-4 py-3">
        <Link href={href} className="font-mono text-[13px] font-semibold text-foreground underline-offset-4 hover:text-accent hover:underline">
          {p.patient_id}
        </Link>
      </td>
      <td className="px-4 py-3 text-muted">{age}</td>
      <td className="px-4 py-3 text-muted">{sexLabel(p.sex)}</td>
      <td className="px-4 py-3 text-muted">{regionLabel(p.region_id)}</td>
      <td className="px-4 py-3">
        <span className="flex flex-col gap-1">
          {programmes.map((pw) => (
            <ProgrammeHistory key={pw} pathway={pw} history={p.history_by_pathway[pw]} compact />
          ))}
          {programmes.length === 0 && <span className="text-xs text-faint">No programme history record</span>}
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
  const btn =
    "inline-flex h-9 items-center gap-1 rounded-md border border-border-strong px-3 text-sm font-medium text-foreground transition-colors hover:border-accent disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border-strong";
  return (
    <nav aria-label="Pagination" className="mt-4 flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-muted">
        Showing <span className="tabular-nums text-foreground">{start}–{start + shown - 1}</span> of{" "}
        <span className="tabular-nums text-foreground">{total}</span>
      </p>
      <div className="flex items-center gap-2">
        <button type="button" className={btn} disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft size={14} aria-hidden="true" /> Previous
        </button>
        <span className="px-1 text-sm tabular-nums text-muted" aria-current="page">
          Page {page} of {lastPage}
        </span>
        <button type="button" className={btn} disabled={page >= lastPage} onClick={() => onPage(page + 1)}>
          Next <ChevronRight size={14} aria-hidden="true" />
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
        className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-on-accent transition-opacity hover:opacity-90"
      >
        {action}
      </button>
    </div>
  );
}

function ResultsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading people" className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="h-9 border-b border-border bg-surface-sunken" />
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex items-center gap-6 border-b border-border px-4 py-3.5 last:border-0">
          <div className="h-4 w-36 animate-pulse rounded bg-surface-sunken" style={{ animationDelay: `${i * 80}ms` }} />
          <div className="h-4 w-16 animate-pulse rounded bg-surface-sunken" />
          <div className="hidden h-4 w-14 animate-pulse rounded bg-surface-sunken sm:block" />
          <div className="hidden h-4 w-40 animate-pulse rounded bg-surface-sunken md:block" />
        </div>
      ))}
    </div>
  );
}
