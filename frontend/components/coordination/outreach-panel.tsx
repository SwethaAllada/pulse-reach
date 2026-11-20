"use client";

import { useState } from "react";
import { Bot, CheckCircle2, FileText, ShieldAlert, XCircle } from "lucide-react";
import { api } from "@/lib/api/client";
import type { CareGapDetailOut, CareTeamMemberOut, OutreachDraftOut, OutreachReviewOut } from "@/lib/api/types";
import { blockedReasonText, formatDateTime, memberName, outreachOutcomeText } from "@/lib/coordination/model";
import { useMutation } from "@/lib/coordination/use-coordination";
import { useAuth } from "@/lib/auth/auth-context";
import { Segmented } from "@/components/ui/segmented";
import { buttonClass } from "@/components/ui/button-styles";
import { PermissionNotice } from "@/components/ui/permission-notice";
import { Confirmation, FormError, StatusPill, inputClass, labelClass, textareaClass } from "./primitives";

type Channel = "sms" | "phone" | "email" | "app";
const CHANNEL_LABELS: Record<Channel, string> = { sms: "SMS", phone: "Phone script", email: "E-mail", app: "App" };

/**
 * AI-assisted (or deterministic template) outreach draft → human edit → approve or reject.
 * The backend gates consent, channel, language and next step before any generation and again at
 * approval; approval records a *simulated* attempt. Nothing is ever sent or delivered.
 */
export function OutreachPanel({
  patientId,
  gap,
  preferredChannel,
  preferredLanguage,
  team,
  open,
}: {
  patientId: string;
  gap: CareGapDetailOut;
  preferredChannel: string | null;
  preferredLanguage: string | null;
  team: Map<string, CareTeamMemberOut> | null;
  /** Gap is open and the task is not closed. */
  open: boolean;
}) {
  const { can } = useAuth();
  const initialChannel = (["sms", "phone", "email", "app"] as Channel[]).includes(preferredChannel as Channel) ? (preferredChannel as Channel) : "sms";
  const [channel, setChannel] = useState<Channel>(initialChannel);
  const [language, setLanguage] = useState<"en" | "ar">(preferredLanguage === "ar" ? "ar" : "en");
  const [tone, setTone] = useState<"supportive" | "neutral">("supportive");
  const [draft, setDraft] = useState<OutreachDraftOut | null>(null);
  const [body, setBody] = useState("");
  const [reason, setReason] = useState("");
  const [review, setReview] = useState<OutreachReviewOut | null>(null);
  const generate = useMutation();
  const decide = useMutation();
  const history = gap.follow_up_events.filter((f) => f.event_type === "outreach_attempted" || f.event_type === "outreach_suppressed");

  const runDraft = async () => {
    setReview(null);
    const d = await generate.run(() =>
      api.outreachDraft({ patient_id: patientId, rule_id: gap.rule_id, care_gap_id: gap.care_gap_id, channel, language, tone })
    );
    if (d) {
      setDraft(d);
      setBody(d.draft_body ?? "");
    }
  };

  const runReview = async (decision: "approved" | "rejected") => {
    if (!draft?.ai?.audit_id) return;
    const r = await decide.run(() =>
      api.outreachReview({
        draft_audit_id: draft.ai!.audit_id!,
        patient_id: patientId,
        rule_id: gap.rule_id,
        care_gap_id: gap.care_gap_id,
        channel: draft.channel ?? channel,
        language: draft.language ?? language,
        decision,
        ...(decision === "approved" ? { final_message: body } : { reason: reason || undefined }),
      })
    );
    if (r) setReview(r);
  };

  return (
    <div className="flex flex-col gap-5">
      <p className="flex items-start gap-2 rounded-xl border border-dashed border-border-strong px-3 py-2 text-xs leading-relaxed text-muted">
        <ShieldAlert size={14} aria-hidden="true" className="mt-px shrink-0 text-status-review" />
        Simulated outreach only. PulseReach never sends SMS, e-mail, calls or notifications. A draft must be reviewed by a
        person; AI wording never decides eligibility, risk or completion.
      </p>

      {!can("outreach.draft") ? (
        <PermissionNotice title="Outreach drafting is not available for your role" permission="outreach.draft" />
      ) : !open ? (
        <p className="text-sm text-muted">Drafting is available only while the care gap and the follow-up are open.</p>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className={labelClass}>
              Channel
              <select className={inputClass} value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
                {(Object.keys(CHANNEL_LABELS) as Channel[]).map((c) => (
                  <option key={c} value={c}>
                    {CHANNEL_LABELS[c]}
                    {c === preferredChannel ? " (patient preference)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <div className={labelClass}>
              Language
              <Segmented label="Draft language" options={[{ value: "en", label: "English" }, { value: "ar", label: "العربية" }]} value={language} onChange={setLanguage} className="w-full" />
            </div>
            <div className={labelClass}>
              Tone
              <Segmented label="Draft tone" options={[{ value: "supportive", label: "Supportive" }, { value: "neutral", label: "Neutral" }]} value={tone} onChange={setTone} className="w-full" />
            </div>
          </div>
          <div>
            <button type="button" className={buttonClass("secondary")} onClick={runDraft} disabled={generate.pending}>
              <Bot size={15} aria-hidden="true" /> {generate.pending ? "Preparing draft…" : draft ? "Prepare a new draft" : "Prepare draft"}
            </button>
          </div>
          <FormError message={generate.error} />
        </div>
      )}

      {draft && !draft.allowed && (
        <div role="status" className="reveal flex items-start gap-2 rounded-xl border border-border bg-surface-sunken px-3 py-2.5 text-sm text-muted">
          <XCircle size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-status-not-eligible" />
          <span>
            <span className="font-medium text-foreground">No draft — outreach is blocked.</span> {blockedReasonText(draft.blocked_reason)}
          </span>
        </div>
      )}

      {draft?.allowed && !review && (
        <div className="reveal flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill tone="review" label="Draft · awaiting human review" />
            <span className="inline-flex items-center gap-1 text-xs text-muted">
              {draft.is_fallback ? <FileText size={12} aria-hidden="true" /> : <Bot size={12} aria-hidden="true" />}
              {draft.is_fallback ? "Approved template (AI unavailable or disabled)" : "AI-assisted wording"} · {CHANNEL_LABELS[(draft.channel as Channel) ?? channel]} ·{" "}
              {draft.language === "ar" ? "Arabic" : "English"}
            </span>
          </div>
          <label className={labelClass}>
            Message for review (editable)
            <textarea
              className={`${textareaClass} min-h-32 normal-case tracking-normal`}
              dir={draft.language === "ar" ? "rtl" : "ltr"}
              lang={draft.language ?? undefined}
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </label>
          <p className="text-xs text-faint">{draft.disclaimer}</p>
          {can("outreach.review") ? (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap gap-2">
                <button type="button" className={buttonClass("primary")} onClick={() => runReview("approved")} disabled={decide.pending || !body.trim()}>
                  <CheckCircle2 size={15} aria-hidden="true" /> Approve (simulated, not sent)
                </button>
                <button type="button" className={buttonClass("secondary")} onClick={() => runReview("rejected")} disabled={decide.pending}>
                  Reject draft
                </button>
              </div>
              <label className={labelClass}>
                Rejection reason (optional, not stored as text)
                <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
            </div>
          ) : (
            <PermissionNotice title="Reviewing drafts needs a reviewer" permission="outreach.review" />
          )}
          <FormError message={decide.error} />
        </div>
      )}

      {review && (
        <Confirmation>
          {review.review_status === "approved" ? (
            <>
              Approved by you{review.edited ? " (edited)" : ""}. Outreach status: <strong>{outreachOutcomeText(review.simulated_outreach_status)}</strong>. Delivered:{" "}
              <strong>no</strong> — PulseReach does not send messages.
            </>
          ) : review.review_status === "rejected" ? (
            <>Draft rejected. Nothing was recorded as outreach.</>
          ) : (
            <>Approval blocked: {blockedReasonText(review.blocked_reason)} Nothing was recorded as outreach.</>
          )}
        </Confirmation>
      )}

      <div>
        <h4 className="text-xs font-medium text-faint">Review history for this care gap</h4>
        {history.length === 0 ? (
          <p className="mt-2 text-sm text-muted">No outreach has been reviewed for this care gap.</p>
        ) : (
          <ul className="mt-2 flex flex-col divide-y divide-border">
            {history.map((f) => (
              <li key={f.follow_up_id} className="flex flex-wrap items-baseline justify-between gap-2 py-2 text-sm">
                <span className="text-foreground">
                  {f.event_type === "outreach_attempted" ? "Approved" : "Suppressed"} · {outreachOutcomeText(f.outcome_status ?? f.event_type)}
                  {f.suppression_reason && <span className="text-muted"> · {blockedReasonText(f.suppression_reason)}</span>}
                </span>
                <span className="text-xs text-muted">
                  Reviewer {memberName(team, f.recorded_by)} · {formatDateTime(f.recorded_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
