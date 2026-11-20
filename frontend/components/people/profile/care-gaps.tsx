"use client";

import { useState } from "react";
import { ArrowDownRight, ChevronDown, LoaderCircle, Route } from "lucide-react";
import type { CareGapOut } from "@/lib/api/types";
import { Surface } from "@/components/ui/surface";
import { StatusGlyph } from "@/components/ui/status-glyph";
import { pathwayLabel } from "@/lib/population/filters";
import { ruleShortLabel } from "@/lib/population/model";
import {
  gapEvidenceRefs,
  gapStatusMeta,
  gapTypeMeta,
  reasonCodeLabel,
  ruleServices,
  type PathwayEntry,
  type TraceItem,
} from "@/lib/people/person";
import { useRuleDetail, type PersonProfileData } from "@/lib/people/use-people-data";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { useMutation } from "@/lib/coordination/use-coordination";
import { buttonClass } from "@/components/ui/button-styles";
import { Confirmation, FormError, inputClass, labelClass } from "@/components/coordination/primitives";
import { cn } from "@/lib/cn";
import { ProfileSection, UnavailableNote } from "./profile-section";

export function CareGapsSection({
  data,
  pathways,
  onTrace,
}: {
  data: PersonProfileData;
  pathways: PathwayEntry[];
  onTrace: (evaluationId: string) => void;
}) {
  const gaps = data.evaluations.care_gaps;
  const open = gaps.filter((g) => gapStatusMeta(g.status).isOpen);
  const closed = gaps.filter((g) => !gapStatusMeta(g.status).isOpen);
  const byGap = new Map(pathways.map((p) => [p.gap.care_gap_id, p]));
  /* Kept here: a documented completion closes the gap, so its card moves to the closed group and remounts. */
  const [documented, setDocumented] = useState<{ gapId: string; evidence: string } | null>(null);

  return (
    <ProfileSection
      id="care-gaps"
      title="Care Gaps"
      description="Care-gap records produced by the deterministic engine for this person. Only “Closed — completed” means a service was documented as done."
    >
      {documented && (
        <div className="mb-4">
          <Confirmation>
            Completion documented on <span className="font-mono">{documented.gapId}</span> with evidence{" "}
            <span className="font-mono">{documented.evidence}</span>. The engine re-checked the rule; a linked follow-up is completed from
            its task page.
          </Confirmation>
        </div>
      )}
      {gaps.length === 0 ? (
        <p className="rounded-md border border-dashed border-border-strong px-4 py-3 text-sm text-muted">
          No care-gap records for this person in evaluation run {data.evaluations.evaluation_run_id}. This does not mean every
          recommended service was completed — see the evidence trace for unknown or review results.
        </p>
      ) : (
        <div className="flex flex-col gap-6">
          {[
            { title: "Open", list: open },
            { title: "Closed or inactive", list: closed },
          ].map(
            (group) =>
              group.list.length > 0 && (
                <div key={group.title}>
                  <h3 className="mb-2 text-sm font-semibold text-foreground">
                    {group.title} <span className="font-mono text-xs text-faint">({group.list.length})</span>
                  </h3>
                  <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                    {group.list.map((g) => (
                      <li key={g.care_gap_id}>
                        <GapCard gap={g} data={data} pathway={byGap.get(g.care_gap_id)} onTrace={onTrace} onDocumented={setDocumented} />
                      </li>
                    ))}
                  </ul>
                </div>
              )
          )}
        </div>
      )}
    </ProfileSection>
  );
}

function GapCard({
  gap,
  data,
  pathway,
  onTrace,
  onDocumented,
}: {
  gap: CareGapOut;
  data: PersonProfileData;
  pathway: PathwayEntry | undefined;
  onTrace: (evaluationId: string) => void;
  onDocumented: (done: { gapId: string; evidence: string }) => void;
}) {
  const rule = data.rules.get(gap.rule_id);
  const status = gapStatusMeta(gap.status);
  const type = gapTypeMeta(gap.gap_type);
  const refs = gapEvidenceRefs(gap);
  return (
    <Surface className={cn("flex h-full flex-col p-4", !status.isOpen && "bg-surface-sunken")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-faint">
            {type.label} · {rule ? pathwayLabel(rule.pathway, true) : "Programme unknown"}
          </p>
          <h4 className="mt-0.5 text-sm font-semibold text-foreground">{ruleShortLabel(rule, gap.rule_id)}</h4>
          <p className="font-mono text-xs text-muted">
            {gap.rule_id} v{gap.rule_version}
          </p>
        </div>
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs text-foreground">
          <StatusGlyph status={status.glyph} size={12} />
          {status.label}
        </span>
      </div>
      <p className="mt-2 text-sm text-muted">{type.description}</p>
      <p className="mt-1 text-xs text-muted">{status.description}</p>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div>
          <dt className="text-faint">Identified</dt>
          <dd className="text-foreground">{gap.identified_date}</dd>
        </div>
        <div>
          <dt className="text-faint">Closed</dt>
          <dd className="text-foreground">{gap.closed_date ?? "—"}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-faint">Evidence</dt>
          <dd className="text-foreground">
            {refs.length === 0
              ? "No linked record — the gap reflects the absence of a qualifying documented record."
              : refs.map((r) => (
                  <span key={r.id} className="block">
                    {r.label} <span className="font-mono">{r.id}</span>
                  </span>
                ))}
          </dd>
        </div>
        <div className="col-span-2">
          <dt className="text-faint">Next step</dt>
          <dd className="text-foreground">
            {pathway?.offered ? (
              <a href="#pathway" className="font-medium text-accent hover:text-foreground">
                Supported pathway available — see Recommended Pathway
              </a>
            ) : (
              (pathway?.blocked ?? "No supported next step.")
            )}
          </dd>
        </div>
      </dl>
      <button
        type="button"
        onClick={() => onTrace(gap.evaluation_id)}
        className="mt-auto inline-flex w-fit items-center gap-1 pt-3 text-xs font-medium text-accent transition-colors hover:text-foreground"
      >
        <ArrowDownRight size={13} aria-hidden="true" /> Trace the evidence for this gap
      </button>
      {status.isOpen && <DocumentCompletion gap={gap} onDocumented={onDocumented} />}
    </Surface>
  );
}

/**
 * Documented completion on the care gap itself (`care_gaps.complete`): clinicians record evidence
 * without follow-up management rights. The backend re-runs the gap's rule on the cited record and
 * refuses mismatched or future evidence; a linked follow-up is completed from its task page.
 */
function DocumentCompletion({ gap, onDocumented }: { gap: CareGapOut; onDocumented: (done: { gapId: string; evidence: string }) => void }) {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [evidence, setEvidence] = useState("");
  const [note, setNote] = useState("");
  const { run, pending, error } = useMutation();
  if (!can("care_gaps.complete")) return null;
  if (!open)
    return (
      <button type="button" className={buttonClass("secondary", "mt-3 self-start")} onClick={() => setOpen(true)}>
        Document completion
      </button>
    );
  return (
    <form
      aria-label={`Document completion for ${gap.care_gap_id}`}
      className="mt-3 flex flex-col gap-3 border-t border-border pt-3"
      onSubmit={async (e) => {
        e.preventDefault();
        const out = await run(() =>
          api.createCareGapFollowUp(gap.care_gap_id, {
            event_type: "completion_documented",
            close_gap: true,
            documented_evidence: true,
            evidence_reference: evidence.trim(),
            note: note.trim() || null,
          })
        );
        if (out) {
          setOpen(false);
          onDocumented({ gapId: gap.care_gap_id, evidence: evidence.trim() });
        }
      }}
    >
      <label className={labelClass}>
        Evidence record ID
        <input className={`${inputClass} font-mono`} required value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="SYNTH-SCR-… / SYNTH-VIS-… / SYNTH-REF-…" />
        <span className="normal-case tracking-normal text-faint">The completed record must belong to this person and satisfy the gap’s rule.</span>
      </label>
      <label className={labelClass}>
        Note (internal)
        <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <FormError message={error} />
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={buttonClass("primary")} disabled={pending || !evidence.trim()}>
          {pending ? "Checking evidence…" : "Document completion and close"}
        </button>
        <button type="button" className={buttonClass("quiet")} onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function PathwaySection({
  data,
  pathways,
  trace,
}: {
  data: PersonProfileData;
  pathways: PathwayEntry[];
  trace: TraceItem[];
}) {
  const offered = pathways.filter((p) => p.offered);
  const notOffered = pathways.filter((p) => !p.offered && gapStatusMeta(p.gap.status).isOpen);
  const missing = new Map<string, number>();
  for (const t of trace.filter((i) => i.origin === "person_evidence")) {
    const code = t.evaluation.reason_code ?? t.evaluation.reasons[0]?.reason_code ?? t.evaluation.evaluation_status;
    missing.set(code, (missing.get(code) ?? 0) + 1);
  }

  return (
    <ProfileSection
      id="pathway"
      title="Recommended Pathway"
      description="Preventive-care services defined by the configured programme rules for open, due gaps under verified, authoritative rules. PulseReach does not generate independent clinical recommendations."
    >
      <div className="flex flex-col gap-4">
        {offered.length === 0 ? (
          <UnavailableNote title="No supported pathway for this person">
            {notOffered.length === 0
              ? "There are no open documented care gaps, so no rule-defined pathway applies. No recommendation is generated in its place."
              : "None of the open gaps meets the conditions for a rule-defined pathway (open, due, verified and authoritative). Reasons are listed below."}
          </UnavailableNote>
        ) : (
          <ul className="flex flex-col gap-3">
            {offered.map((p) => (
              <li key={p.gap.care_gap_id}>
                <PathwayCard entry={p} />
              </li>
            ))}
          </ul>
        )}

        {notOffered.length > 0 && (
          <Surface className="p-4">
            <h3 className="text-sm font-semibold text-foreground">Open gaps without a supported pathway</h3>
            <ul className="mt-2 flex flex-col divide-y divide-border">
              {notOffered.map((p) => (
                <li key={p.gap.care_gap_id} className="py-2 text-sm">
                  <span className="font-mono text-xs text-foreground">{p.gap.rule_id}</span>
                  <span className="block text-muted">{p.blocked}</span>
                </li>
              ))}
            </ul>
          </Surface>
        )}

        {missing.size > 0 && (
          <Surface className="p-4">
            <h3 className="text-sm font-semibold text-foreground">Information still required</h3>
            <p className="mt-0.5 text-xs text-muted">Results that could not be determined for this person, by reason.</p>
            <ul className="mt-2 flex flex-col gap-1 text-sm">
              {[...missing.entries()].map(([code, n]) => (
                <li key={code} className="flex justify-between gap-3">
                  <span className="text-foreground">{reasonCodeLabel(code)}</span>
                  <span className="font-mono text-xs tabular-nums text-muted">
                    {n} {n === 1 ? "rule" : "rules"}
                  </span>
                </li>
              ))}
            </ul>
          </Surface>
        )}

        <p className="text-xs text-faint">
          Follow-ups, simulated outreach and appointment records for these gaps are under Care Coordination; referral creation is not available. Evaluation run{" "}
          {data.evaluations.evaluation_run_id}.
        </p>
      </div>
    </ProfileSection>
  );
}

function PathwayCard({ entry }: { entry: PathwayEntry }) {
  const [showServices, setShowServices] = useState(false);
  const { gap, rule, evaluation } = entry;
  const detail = useRuleDetail(gap.rule_id, showServices);
  if (!rule || !evaluation) return null;
  const panelId = `pathway-services-${gap.care_gap_id}`;
  return (
    <Surface className="p-5">
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
          <Route size={18} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-faint">{pathwayLabel(rule.pathway)}</p>
          <h3 className="text-sm font-semibold text-foreground">{ruleShortLabel(rule, rule.rule_id)}</h3>
          <dl className="mt-3 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-faint">Why it applies</dt>
              <dd className="text-foreground">
                Evaluated as due{evaluation.next_due_date ? ` (next date per rule ${evaluation.next_due_date})` : ""};{" "}
                {gapTypeMeta(gap.gap_type).label.toLowerCase()}.
              </dd>
            </div>
            <div>
              <dt className="text-xs text-faint">Supporting rule</dt>
              <dd className="text-foreground">
                <span className="font-mono text-xs">
                  {rule.rule_id} v{rule.rule_version}
                </span>
                <span className="block text-xs text-muted">{rule.source_reference}</span>
              </dd>
            </div>
            <div>
              <dt className="text-xs text-faint">Available next step</dt>
              <dd className="text-muted">
                Create a follow-up under{" "}
                <a href="#coordination" className="text-accent underline-offset-4 hover:underline">
                  Care Coordination
                </a>
                ; the rule’s documented step is shown on the follow-up.
              </dd>
            </div>
            <div>
              <dt className="text-xs text-faint">Information still required</dt>
              <dd className="text-muted">None reported by the engine for this rule.</dd>
            </div>
          </dl>
          <button
            type="button"
            aria-expanded={showServices}
            aria-controls={panelId}
            onClick={() => setShowServices((v) => !v)}
            className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-accent transition-colors hover:text-foreground"
          >
            Services listed by the rule
            <ChevronDown size={13} aria-hidden="true" className={cn("transition-transform", showServices && "rotate-180")} />
          </button>
          {showServices && (
            <div id={panelId} className="mt-2 text-sm">
              {detail.state?.status === "loading" && (
                <p className="flex items-center gap-2 text-xs text-muted">
                  <LoaderCircle size={12} aria-hidden="true" className="animate-spin" /> Loading rule definition…
                </p>
              )}
              {detail.state?.status === "error" && <p className="text-xs text-muted">Unavailable: {detail.state.message}</p>}
              {detail.state?.status === "ready" &&
                (() => {
                  const groups = ruleServices(detail.state.data);
                  return groups.length === 0 ? (
                    <p className="text-xs text-muted">The rule definition lists no individual services.</p>
                  ) : (
                    groups.map((g) => (
                      <div key={g.category} className="mt-2">
                        <p className="text-xs font-medium text-faint">{g.category}</p>
                        <ul className="mt-1 flex flex-wrap gap-1.5">
                          {g.items.map((it, i) => (
                            <li
                              key={i}
                              className={cn(
                                "rounded-md border px-2 py-0.5 text-xs",
                                it.verified ? "border-border text-foreground" : "border-dashed border-border-strong text-muted"
                              )}
                            >
                              {it.description}
                              {!it.verified && " (not verified)"}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))
                  );
                })()}
            </div>
          )}
        </div>
      </div>
    </Surface>
  );
}
