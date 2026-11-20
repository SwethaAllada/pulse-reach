"use client";

import { useEffect, useMemo, useState } from "react";
import { CalendarPlus, Info, Search } from "lucide-react";
import { api, apiErrorMessage } from "@/lib/api/client";
import type { AppointmentOut, AppointmentType, CareGapOut, ServiceProfileOut } from "@/lib/api/types";
import { APPOINTMENT_TYPE_LABELS, gapTypeText } from "@/lib/coordination/model";
import { useMutation, useServiceProfiles } from "@/lib/coordination/use-coordination";
import { buttonClass } from "@/components/ui/button-styles";
import { FormError, inputClass, labelClass, textareaClass } from "./primitives";
import { t as activeT, type Translate } from "@/lib/i18n/translate";
import { useLocale } from "@/lib/i18n/use-locale";

export function profileLabel(p: ServiceProfileOut | undefined, id: string, t: Translate): string {
  if (!p) return id;
  return `${p.facility_name ?? t("coord.schedule.facility_n", { id: String(p.facility_id) })} · ${id}`;
}

function slotFor(local: string): "weekday" | "evening" | "weekend" {
  if (!local) return "weekday";
  const d = new Date(`${local}:00Z`);
  const day = d.getUTCDay();
  if (day === 0 || day === 6) return "weekend";
  return d.getUTCHours() >= 17 ? "evening" : "weekday";
}

/**
 * Records an appointment (`POST /appointments`) against a simulated service profile. There is no
 * availability or booking engine: the record coordinates care, it is not a provider confirmation.
 */
export function ScheduleForm({
  patientId: fixedPatient,
  careGapId,
  suggestedDate,
  onCreated,
  onCancel,
  submitLabel,
}: {
  patientId?: string;
  careGapId?: string | null;
  /** ISO date the patient preferred, if any. */
  suggestedDate?: string | null;
  onCreated: (a: AppointmentOut) => void | Promise<void>;
  onCancel: () => void;
  submitLabel?: string;
}) {
  const { t } = useLocale();
  const profiles = useServiceProfiles();
  const [patient, setPatient] = useState(fixedPatient ?? "");
  const [gaps, setGaps] = useState<CareGapOut[] | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [gapId, setGapId] = useState(careGapId ?? "");
  const [type, setType] = useState<AppointmentType>("ifhas_screening");
  const [profile, setProfile] = useState("");
  const [when, setWhen] = useState(suggestedDate ? `${suggestedDate}T09:00` : "");
  const [slot, setSlot] = useState<"weekday" | "evening" | "weekend" | null>(null);
  const [note, setNote] = useState("");
  const { run, pending, error } = useMutation();

  const lookup = async (pid: string) => {
    if (!pid.trim()) return;
    setLookupError(null);
    try {
      const ev = await api.patientEvaluations(pid.trim());
      const open = ev.care_gaps.filter((g) => g.status === "open");
      setGaps(open);
      const g = open.find((x) => x.care_gap_id === careGapId);
      if (g) setType(g.rule_id.startsWith("WCV") ? "well_child_visit" : "ifhas_screening");
    } catch (err) {
      setGaps(null);
      setLookupError(apiErrorMessage(err, activeT("coord.person_not_loaded")));
    }
  };

  useEffect(() => {
    // Deferred: the lookup updates state once the requests settle, not during the effect.
    if (fixedPatient) void Promise.resolve(fixedPatient).then(lookup);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fixedPatient]);

  const items = useMemo(() => (profiles.status === "ready" ? profiles.data.items : []), [profiles]);
  const offered = items.filter((p) => (type === "ifhas_screening" ? p.offers_ifhas : type === "well_child_visit" ? p.offers_wcv : true));
  const slotType = slot ?? slotFor(when);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const a = await run(() =>
      api.createAppointment({
        patient_id: patient.trim(),
        profile_id: profile,
        care_gap_id: gapId || null,
        appointment_type: type,
        scheduled_datetime: new Date(`${when}:00Z`).toISOString(),
        slot_type: slotType,
        note: note.trim() || null,
      })
    );
    if (a) await onCreated(a);
  };

  return (
    <form onSubmit={submit} aria-label={t("coord.record_appointment")} className="reveal flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
      <p className="flex items-start gap-2 text-xs leading-relaxed text-muted">
        <Info size={14} aria-hidden="true" className="mt-px shrink-0 text-status-info" />
        {profiles.status === "ready"
          ? profiles.data.notice
          : t("coord.schedule.notice_fallback")}
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className={`${labelClass} w-full sm:w-72`}>
          {t("coord.person_id_synthetic")}
          <input
            className={`${inputClass} font-mono`}
            value={patient}
            readOnly={!!fixedPatient}
            required
            onChange={(e) => setPatient(e.target.value)}
            onBlur={() => !fixedPatient && void lookup(patient)}
            autoComplete="off"
          />
        </label>
        {!fixedPatient && (
          <button type="button" className={buttonClass("secondary")} onClick={() => void lookup(patient)}>
            <Search size={14} aria-hidden="true" /> {t("coord.schedule.look_up_gaps")}
          </button>
        )}
      </div>
      <FormError message={lookupError} />
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className={labelClass}>
          {t("coord.care_gap")}
          <select className={inputClass} value={gapId} onChange={(e) => setGapId(e.target.value)}>
            <option value="">{t("coord.not_linked_gap")}</option>
            {(gaps ?? []).map((g) => (
              <option key={g.care_gap_id} value={g.care_gap_id}>
                {g.rule_id} · {gapTypeText(g.gap_type, t)}
              </option>
            ))}
            {careGapId && !(gaps ?? []).some((g) => g.care_gap_id === careGapId) && <option value={careGapId}>{careGapId}</option>}
          </select>
        </label>
        <label className={labelClass}>
          {t("coord.schedule.type")}
          <select className={inputClass} value={type} onChange={(e) => setType(e.target.value as AppointmentType)}>
            {(Object.keys(APPOINTMENT_TYPE_LABELS) as AppointmentType[]).map((k) => (
              <option key={k} value={k}>
                {t(APPOINTMENT_TYPE_LABELS[k])}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          {t("coord.schedule.profile")}
          <select className={inputClass} required value={profile} onChange={(e) => setProfile(e.target.value)}>
            <option value="">{profiles.status === "loading" ? t("coord.loading") : t("coord.schedule.choose_profile")}</option>
            {offered.map((p) => (
              <option key={p.profile_id} value={p.profile_id}>
                {[profileLabel(p, p.profile_id, t), p.evening_hours && t("coord.schedule.evenings"), p.weekend_hours && t("coord.schedule.weekends")]
                  .filter(Boolean)
                  .join(" · ")}
              </option>
            ))}
          </select>
          {profiles.status === "forbidden" && (
            <span className="normal-case tracking-normal text-faint">{t("coord.schedule.profiles_forbidden", { permission: "facilities.read" })}</span>
          )}
        </label>
        <label className={labelClass}>
          {t("coord.schedule.when")}
          <input type="datetime-local" className={inputClass} required value={when} onChange={(e) => setWhen(e.target.value)} />
        </label>
        <label className={labelClass}>
          {t("coord.schedule.slot")}
          <select className={inputClass} value={slotType} onChange={(e) => setSlot(e.target.value as "weekday" | "evening" | "weekend")}>
            <option value="weekday">{t("coord.slot.weekday")}</option>
            <option value="evening">{t("coord.slot.evening")}</option>
            <option value="weekend">{t("coord.slot.weekend")}</option>
          </select>
        </label>
      </div>
      <label className={labelClass}>
        {t("coord.note_staff_history")}
        <textarea className={textareaClass} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
      </label>
      <FormError message={error} />
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={buttonClass("primary")} disabled={pending || !profile || !when || !patient.trim()}>
          <CalendarPlus size={15} aria-hidden="true" /> {pending ? t("coord.recording") : submitLabel ?? t("coord.record_appointment")}
        </button>
        <button type="button" className={buttonClass("secondary")} onClick={onCancel}>
          {t("coord.cancel")}
        </button>
      </div>
    </form>
  );
}
