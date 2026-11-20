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
import { useLocale } from "@/lib/i18n/use-locale";
import type { MessageKey } from "@/lib/i18n/translate";

type Channel = "sms" | "phone" | "email" | "app";
const CHANNEL_LABELS: Record<Channel, MessageKey> = {
  sms: "coord.draft_channel.sms",
  phone: "coord.draft_channel.phone",
  email: "coord.draft_channel.email",
  app: "coord.draft_channel.app",
};

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
  const { t, rich, locale } = useLocale();
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
        {t("coord.outreach.disclaimer")}
      </p>

      {!can("outreach.draft") ? (
        <PermissionNotice title={t("coord.outreach.no_draft_permission")} permission="outreach.draft" />
      ) : !open ? (
        <p className="text-sm text-muted">{t("coord.outreach.closed")}</p>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className={labelClass}>
              {t("coord.channel")}
              <select className={inputClass} value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
                {(Object.keys(CHANNEL_LABELS) as Channel[]).map((c) => (
                  <option key={c} value={c}>
                    {c === preferredChannel ? t("coord.outreach.channel_pref", { channel: t(CHANNEL_LABELS[c]) }) : t(CHANNEL_LABELS[c])}
                  </option>
                ))}
              </select>
            </label>
            <div className={labelClass}>
              {t("coord.outreach.language")}
              <Segmented label={t("coord.outreach.draft_language")} options={[{ value: "en", label: t("language.en") }, { value: "ar", label: t("language.ar") }]} value={language} onChange={setLanguage} className="w-full" />
            </div>
            <div className={labelClass}>
              {t("coord.outreach.tone")}
              <Segmented
                label={t("coord.outreach.draft_tone")}
                options={[{ value: "supportive", label: t("coord.outreach.supportive") }, { value: "neutral", label: t("coord.outreach.neutral") }]}
                value={tone}
                onChange={setTone}
                className="w-full"
              />
            </div>
          </div>
          <div>
            <button type="button" className={buttonClass("secondary")} onClick={runDraft} disabled={generate.pending}>
              <Bot size={15} aria-hidden="true" /> {generate.pending ? t("coord.outreach.preparing") : draft ? t("coord.outreach.prepare_new") : t("coord.outreach.prepare")}
            </button>
          </div>
          <FormError message={generate.error} />
        </div>
      )}

      {draft && !draft.allowed && (
        <div role="status" className="reveal flex items-start gap-2 rounded-xl border border-border bg-surface-sunken px-3 py-2.5 text-sm text-muted">
          <XCircle size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-status-not-eligible" />
          <span>
            <span className="font-medium text-foreground">{t("coord.outreach.blocked")}</span> {blockedReasonText(draft.blocked_reason, t)}
          </span>
        </div>
      )}

      {draft?.allowed && !review && (
        <div className="reveal flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill tone="review" label={t("coord.outreach.awaiting_review")} />
            <span className="inline-flex items-center gap-1 text-xs text-muted">
              {draft.is_fallback ? <FileText size={12} aria-hidden="true" /> : <Bot size={12} aria-hidden="true" />}
              {draft.is_fallback ? t("coord.outreach.fallback") : t("coord.outreach.ai_assisted")} ·{" "}
              {CHANNEL_LABELS[(draft.channel as Channel) ?? channel] ? t(CHANNEL_LABELS[(draft.channel as Channel) ?? channel]) : draft.channel} ·{" "}
              {t(draft.language === "ar" ? "coord.lang.ar" : "coord.lang.en")}
            </span>
          </div>
          <label className={labelClass}>
            {t("coord.outreach.message_review")}
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
                  <CheckCircle2 size={15} aria-hidden="true" /> {t("coord.outreach.approve")}
                </button>
                <button type="button" className={buttonClass("secondary")} onClick={() => runReview("rejected")} disabled={decide.pending}>
                  {t("coord.outreach.reject")}
                </button>
              </div>
              <label className={labelClass}>
                {t("coord.outreach.reject_reason")}
                <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
            </div>
          ) : (
            <PermissionNotice title={t("coord.outreach.no_review_permission")} permission="outreach.review" />
          )}
          <FormError message={decide.error} />
        </div>
      )}

      {review && (
        <Confirmation>
          {review.review_status === "approved" ? (
            rich(review.edited ? "coord.outreach.approved_edited" : "coord.outreach.approved", {
              status: <strong>{outreachOutcomeText(review.simulated_outreach_status, t)}</strong>,
              no: <strong>{t("coord.outreach.no")}</strong>,
            })
          ) : review.review_status === "rejected" ? (
            t("coord.outreach.rejected")
          ) : (
            t("coord.outreach.approval_blocked", { reason: blockedReasonText(review.blocked_reason, t) })
          )}
        </Confirmation>
      )}

      <div>
        <h4 className="text-xs font-medium text-faint">{t("coord.outreach.history")}</h4>
        {history.length === 0 ? (
          <p className="mt-2 text-sm text-muted">{t("coord.outreach.no_history")}</p>
        ) : (
          <ul className="mt-2 flex flex-col divide-y divide-border">
            {history.map((f) => (
              <li key={f.follow_up_id} className="flex flex-wrap items-baseline justify-between gap-2 py-2 text-sm">
                <span className="text-foreground">
                  {t(f.event_type === "outreach_attempted" ? "coord.outreach.history_approved" : "coord.outreach.history_suppressed")} ·{" "}
                  {outreachOutcomeText(f.outcome_status ?? f.event_type, t)}
                  {f.suppression_reason && <span className="text-muted"> · {blockedReasonText(f.suppression_reason, t)}</span>}
                </span>
                <span className="text-xs text-muted">
                  {t("coord.outreach.reviewer", { name: memberName(team, f.recorded_by, t) })} · {formatDateTime(f.recorded_at, locale)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
