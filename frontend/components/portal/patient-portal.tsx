"use client";

import { useState } from "react";
import {
  CalendarClock,
  ChevronRight,
  ClipboardCheck,
  FileHeart,
  HeartPulse,
  Home,
  Inbox,
  LifeBuoy,
  LogOut,
  MessageSquare,
} from "lucide-react";
import { portalApi, apiErrorMessage } from "@/lib/api/client";
import { useResource, type Resource } from "@/lib/api/resource";
import type { AssistantTopic, PortalAssistantTopic, PatientRequestOut, PatientResponse, PortalAppointmentOut, PortalFollowUpOut, RecommendationOut, TimeOfDay } from "@/lib/api/portal-types";
import { useAuth } from "@/lib/auth/auth-context";
import { useLocale } from "@/lib/i18n/use-locale";
import type { MessageKey } from "@/lib/i18n/translate";
import { LanguageSwitcher } from "@/components/i18n/language-switcher";
import { LogoMark, LogoWordmark } from "@/components/shell/logo";
import { SyntheticBanner } from "@/components/shell/synthetic-banner";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { Plate } from "@/components/ui/plate";
import { KpiCard } from "@/components/ui/figure";
import { buttonClass } from "@/components/ui/button-styles";
import { ResourceView } from "@/components/programmes/resource-state";
import { Confirmation, FormError, QuietEmpty, inputClass, labelClass, textareaClass } from "@/components/coordination/primitives";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-locale";
import { AssistantPanel } from "./portal-assistant";

type View = "home" | "care" | "appointments" | "messages" | "requests" | "record";

const VIEWS: { id: View; label: MessageKey; icon: typeof Home }[] = [
  { id: "home", label: "portal.nav.home", icon: Home },
  { id: "care", label: "portal.nav.care", icon: ClipboardCheck },
  { id: "appointments", label: "portal.nav.appointments", icon: CalendarClock },
  { id: "messages", label: "portal.nav.messages", icon: MessageSquare },
  { id: "requests", label: "portal.nav.requests", icon: Inbox },
  { id: "record", label: "portal.nav.record", icon: FileHeart },
];

/**
 * The patient portal: a separate experience for PATIENT accounts. Every call goes to
 * `/portal/*`, where the backend derives the patient from the verified account link; staff
 * endpoints are never called with a patient session.
 */
export function PatientPortal() {
  const { state, signOut, retry } = useAuth();
  const { t } = useLocale();
  const me = state.status === "signed_in" ? state.me : null;
  const [view, setView] = useState<View>("home");
  const [attempt, setAttempt] = useState(0);
  const bump = () => setAttempt((n) => n + 1);

  return (
    <div className="flex min-h-screen flex-col">
      <SyntheticBanner />
      <header className="sticky top-0 z-30 border-b border-border bg-[color-mix(in_srgb,var(--bg)_88%,transparent)] backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-[1120px] items-center gap-3 px-4 sm:px-6">
          <LogoMark />
          <div className="min-w-0">
            <LogoWordmark />
            <p className="text-[11px] text-faint">{t("portal.subtitle")}</p>
          </div>
          <div className="ms-auto flex items-center gap-2">
            <span className="hidden text-sm text-muted sm:inline">{me?.user.full_name}</span>
            <LanguageSwitcher />
            <ThemeToggle />
            <button type="button" className={buttonClass("secondary")} onClick={() => void signOut()}>
              <LogOut size={14} aria-hidden="true" className="rtl:-scale-x-100" /> {t("user.sign_out")}
            </button>
          </div>
        </div>
        {me?.patient_linked && (
          <nav aria-label={t("portal.nav.label")} className="mx-auto flex max-w-[1120px] gap-1 overflow-x-auto px-4 sm:px-6">
            {VIEWS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                aria-current={view === id ? "page" : undefined}
                onClick={() => setView(id)}
                className={cn(
                  "relative flex h-11 shrink-0 items-center gap-2 px-3 text-sm transition-colors",
                  view === id ? "font-semibold text-foreground" : "text-muted hover:text-foreground"
                )}
              >
                <Icon size={15} aria-hidden="true" className={view === id ? "text-accent" : undefined} />
                {t(label)}
                <span
                  aria-hidden="true"
                  className={cn("absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-accent transition-transform duration-300", view === id ? "scale-x-100" : "scale-x-0")}
                />
              </button>
            ))}
          </nav>
        )}
      </header>
      <main id="portal-content" className="mx-auto w-full max-w-[1120px] flex-1 px-4 pb-16 pt-6 sm:px-6">
        {!me?.patient_linked ? (
          <LinkAccount onLinked={retry} />
        ) : (
          <div key={`${view}|${attempt}`} className="reveal-fade flex flex-col gap-5">
            {view === "home" && <Overview onNavigate={setView} attempt={attempt} />}
            {view === "care" && <Recommendations attempt={attempt} onChanged={bump} />}
            {view === "appointments" && <Appointments attempt={attempt} onChanged={bump} />}
            {view === "messages" && <Messages attempt={attempt} onChanged={bump} />}
            {view === "requests" && <Requests attempt={attempt} onChanged={bump} />}
            {view === "record" && <HealthRecord attempt={attempt} />}
          </div>
        )}
      </main>
      <footer className="border-t border-border py-4 text-center text-xs text-faint">
        {t("portal.footer")}
      </footer>
    </div>
  );
}

function Title({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <header>
      <h1 className="font-display text-[28px] font-medium tracking-[-0.015em] text-foreground">{title}</h1>
      <p className="mt-1 text-sm text-muted">{subtitle}</p>
    </header>
  );
}

function num<T>(r: Resource<T>, pick: (d: T) => number): number | string {
  return r.status === "ready" ? pick(r.data) : r.status === "loading" ? "…" : "—";
}

/* ── Overview ─────────────────────────────────────────────────────────── */

function Overview({ onNavigate, attempt }: { onNavigate: (v: View) => void; attempt: number }) {
  const { t } = useLocale();
  const summary = useResource(`p-sum|${attempt}`, "patients.read_self", (s) => portalApi.summary(s), attempt);
  const recs = useResource(`p-rec|active|${attempt}`, "patients.read_self", (s) => portalApi.recommendations("active", s), attempt);
  const appts = useResource(`p-appt|${attempt}`, "patients.read_self", (s) => portalApi.appointments(s), attempt);
  const name = summary.status === "ready" ? summary.data.given_name : "";
  const next = appts.status === "ready" ? appts.data.items.filter((a) => ["scheduled", "rescheduled"].includes(a.status)).sort((a, b) => a.scheduled_datetime.localeCompare(b.scheduled_datetime))[0] : undefined;

  return (
    <>
      <Title title={name ? t("portal.home.hello", { name }) : t("portal.home.title")} subtitle={t("portal.home.subtitle")} />
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label={t("portal.home.tile.care")} value={num(summary, (d) => d.open_recommendations)} note={t("portal.home.tile.care_note")} onClick={() => onNavigate("care")} />
        <Tile label={t("portal.home.tile.appointments")} value={num(summary, (d) => d.upcoming_appointments)} note={t("portal.home.tile.appointments_note")} onClick={() => onNavigate("appointments")} />
        <Tile label={t("portal.home.tile.reply")} value={num(summary, (d) => d.awaiting_your_reply)} note={t("portal.home.tile.reply_note")} onClick={() => onNavigate("messages")} />
        <Tile label={t("portal.home.tile.requests")} value={num(summary, (d) => d.open_requests)} note={t("portal.home.tile.requests_note")} onClick={() => onNavigate("requests")} />
      </dl>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Plate title={t("portal.home.next.title")} description={t("portal.home.next.description")} flush>
          <ResourceView resource={recs} what={t("portal.what.recommendations")}>
            {(r) =>
              r.items.length === 0 ? (
                <p className="px-5 py-4 text-sm text-muted">{t("portal.home.next.empty")}</p>
              ) : (
                <ul className="divide-y divide-border">
                  {r.items.slice(0, 4).map((x) => (
                    <li key={x.recommendation_id}>
                      <button type="button" onClick={() => onNavigate("care")} className="group flex w-full items-start gap-3 px-5 py-3.5 text-start transition-colors hover:bg-hover">
                        <HeartPulse size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-warm-text" />
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium text-foreground">{x.title}</span>
                          <span className="block text-xs text-muted">
                            {x.programme_label} · {x.next_step_text}
                          </span>
                        </span>
                        <ChevronRight size={15} aria-hidden="true" className="mt-0.5 text-faint group-hover:text-foreground rtl:-scale-x-100" />
                      </button>
                    </li>
                  ))}
                </ul>
              )
            }
          </ResourceView>
        </Plate>
        <Plate title={t("portal.home.appointment.title")}>
          <ResourceView resource={appts} what={t("portal.what.appointments")}>
            {() =>
              next ? (
                <div>
                  <p className="text-lg font-semibold text-foreground">{next.scheduled_display}</p>
                  <p className="mt-1 text-sm text-muted">
                    {next.appointment_type_label} · {next.status_label}
                  </p>
                  <button type="button" className={buttonClass("secondary", "mt-4")} onClick={() => onNavigate("appointments")}>
                    {t("portal.home.appointment.manage")}
                  </button>
                </div>
              ) : (
                <div>
                  <p className="text-sm text-muted">{t("portal.home.appointment.none")}</p>
                  <button type="button" className={buttonClass("primary", "mt-4")} onClick={() => onNavigate("appointments")}>
                    {t("portal.appointments.request")}
                  </button>
                </div>
              )
            }
          </ResourceView>
        </Plate>
      </div>
      <PortalGuide />
    </>
  );
}

function Tile({ label, value, note, onClick }: { label: string; value: React.ReactNode; note: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="text-start transition-transform duration-200 hover:-translate-y-0.5">
      <KpiCard label={label} value={value} note={note} className="h-full hover:border-accent" />
    </button>
  );
}

/* ── Recommended care ─────────────────────────────────────────────────── */

function Recommendations({ attempt, onChanged }: { attempt: number; onChanged: () => void }) {
  const { t } = useLocale();
  const [status, setStatus] = useState<"active" | "all">("active");
  const [open, setOpen] = useState<string | null>(null);
  const recs = useResource(`p-rec|${status}|${attempt}`, "patients.read_self", (s) => portalApi.recommendations(status, s), attempt);
  return (
    <>
      <Title title={t("portal.care.title")} subtitle={t("portal.care.subtitle")} />
      <div className="flex gap-2">
        {(["active", "all"] as const).map((s) => (
          <button key={s} type="button" aria-pressed={status === s} onClick={() => setStatus(s)} className={cn(buttonClass("secondary"), status === s && "border-accent bg-accent-soft")}>
            {s === "active" ? t("portal.care.filter.open") : t("portal.care.filter.all")}
          </button>
        ))}
      </div>
      <ResourceView resource={recs} what={t("portal.what.recommendations")}>
        {(r) =>
          r.items.length === 0 ? (
            <QuietEmpty title={t("portal.care.empty.title")}>{t("portal.care.empty.body")}</QuietEmpty>
          ) : (
            <ul className="flex flex-col gap-3">
              {r.items.map((x) => (
                <RecommendationCard key={x.recommendation_id} rec={x} open={open === x.recommendation_id} onToggle={() => setOpen(open === x.recommendation_id ? null : x.recommendation_id)} onChanged={onChanged} />
              ))}
            </ul>
          )
        }
      </ResourceView>
    </>
  );
}

function RecommendationCard({ rec, open, onToggle, onChanged }: { rec: RecommendationOut; open: boolean; onToggle: () => void; onChanged: () => void }) {
  const detail = useResource(open ? `p-recd|${rec.recommendation_id}` : null, "patients.read_self", (s) => portalApi.recommendation(rec.recommendation_id, s), 0);
  const [requesting, setRequesting] = useState(false);
  const { t } = useLocale();
  return (
    <li className="rounded-xl border border-border bg-surface-raised">
      <button type="button" aria-expanded={open} onClick={onToggle} className="flex w-full items-start gap-3 px-5 py-4 text-start">
        <HeartPulse size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-warm-text" />
        <span className="min-w-0 flex-1">
          <span dir="auto" className="block font-medium text-foreground">{rec.title}</span>
          <span dir="auto" className="mt-0.5 block text-sm text-muted">{rec.description}</span>
          <span className="mt-2 flex flex-wrap gap-x-3 text-xs text-faint">
            <span>{rec.programme_label}</span>
            <span>{t("portal.care.identified", { date: rec.identified_date_display })}</span>
            <span>{rec.status_label}</span>
          </span>
        </span>
        <ChevronRight size={16} aria-hidden="true" className={cn("mt-1 text-faint transition-transform duration-200 rtl:-scale-x-100", open && "rotate-90")} />
      </button>
      {open && (
        <div className="reveal-fade border-t border-border px-5 py-4">
          <ResourceView resource={detail} what={t("portal.what.details")}>
            {(d) => (
              <div className="grid gap-5 md:grid-cols-2">
                <div>
                  <h3 className="text-xs font-medium text-muted">{t("portal.care.why")}</h3>
                  <ul dir="auto" className="mt-2 list-disc space-y-1 ps-5 text-sm text-foreground">
                    {d.evidence.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                  <p dir="auto" className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-sm text-foreground">
                    <span className="font-medium">{t("portal.care.next_step")}</span> {d.next_step_text}
                  </p>
                </div>
                <div>
                  <h3 className="text-xs font-medium text-muted">{t("portal.care.history")}</h3>
                  <ol dir="auto" className="mt-2 space-y-2 border-s border-border ps-4 text-sm">
                    {d.history.map((h, i) => (
                      <li key={i}>
                        <span className="text-foreground">{h.label}</span> <span className="text-xs text-faint">· {h.occurred_on_display}</span>
                      </li>
                    ))}
                  </ol>
                </div>
                <p className="text-xs text-faint md:col-span-2">{d.disclaimer}</p>
              </div>
            )}
          </ResourceView>
          <RecommendationAssistant recommendationId={rec.recommendation_id} />
          {rec.status === "open" &&
            (requesting ? (
              <AppointmentRequestForm recommendationId={rec.recommendation_id} onDone={() => (setRequesting(false), onChanged())} onCancel={() => setRequesting(false)} />
            ) : (
              <button type="button" className={buttonClass("primary", "mt-4")} onClick={() => setRequesting(true)}>
                <CalendarClock size={15} aria-hidden="true" /> {t("portal.care.request_appointment")}
              </button>
            ))}
        </div>
      )}
    </li>
  );
}

/* ── Assistant ─────────────────────────────────────────────────────────── */

function RecommendationAssistant({ recommendationId }: { recommendationId: string }) {
  const t = useT();
  return (
    <AssistantPanel<AssistantTopic>
      title={t("portal.assistant.title")}
      topics={[
        { id: "why", label: "portal.assistant.topic_why" },
        { id: "meaning", label: "portal.assistant.topic_meaning" },
        { id: "next_steps", label: "portal.assistant.topic_next" },
        { id: "prepare_questions", label: "portal.assistant.topic_questions" },
        { id: "appointments", label: "portal.assistant.topic_appointments" },
      ]}
      ask={(topic, question) => portalApi.assistant(recommendationId, topic, question)}
      renderHelp={(initial, close) => <HelpForm initial={initial} onDone={close} onCancel={close} />}
    />
  );
}

function PortalGuide() {
  const t = useT();
  return (
    <AssistantPanel<PortalAssistantTopic>
      title={t("portal.assistant.guide_title")}
      description={t("portal.assistant.guide_description")}
      topics={[
        { id: "overview", label: "portal.assistant.topic_overview" },
        { id: "portal_help", label: "portal.assistant.topic_portal_help" },
        { id: "contact_care_team", label: "portal.assistant.topic_contact" },
      ]}
      ask={(topic, question) => portalApi.guide(topic, question)}
      renderHelp={(initial, close) => <HelpForm initial={initial} onDone={close} onCancel={close} />}
    />
  );
}

function HelpForm({ initial = "", onDone, onCancel }: { initial?: string; onDone: () => void; onCancel: () => void }) {
  const [msg, setMsg] = useState(initial);
  const [state, setState] = useState<{ pending: boolean; error: string | null; done: string | null }>({ pending: false, error: null, done: null });
  const { t } = useLocale();
  if (state.done) return <div className="mt-3"><Confirmation>{state.done}</Confirmation></div>;
  return (
    <form
      aria-label={t("portal.requests.ask_help")}
      className="reveal mt-3 flex flex-col gap-3 rounded-xl border border-border bg-surface-raised p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setState({ pending: true, error: null, done: null });
        try {
          const out = await portalApi.requestAssistance(msg.trim(), null);
          setState({ pending: false, error: null, done: out.confirmation ?? t("portal.assistant.sent") });
          setTimeout(onDone, 1500);
        } catch (err) {
          setState({ pending: false, error: apiErrorMessage(err), done: null });
        }
      }}
    >
      <label className={labelClass}>
        {t("portal.requests.help_label")}
        <textarea dir="auto" className={textareaClass} maxLength={1000} value={msg} onChange={(e) => setMsg(e.target.value)} required />
      </label>
      <FormError message={state.error} />
      <div className="flex gap-2">
        <button type="submit" className={buttonClass("primary")} disabled={!msg.trim() || state.pending}>
          {state.pending ? t("portal.sending") : t("portal.requests.send")}
        </button>
        <button type="button" className={buttonClass("secondary")} onClick={onCancel}>
          {t("portal.cancel")}
        </button>
      </div>
      <p className="text-xs text-faint">{t("portal.assistant.replies_note")}</p>
    </form>
  );
}

/* ── Appointments ─────────────────────────────────────────────────────── */

function AppointmentRequestForm({ recommendationId, followUpId, onDone, onCancel }: { recommendationId?: string; followUpId?: string; onDone: () => void; onCancel: () => void }) {
  const [date, setDate] = useState("");
  const [time, setTime] = useState<TimeOfDay | "">("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const { t } = useLocale();
  if (done) return <div className="mt-4"><Confirmation>{done}</Confirmation></div>;
  return (
    <form
      aria-label={t("portal.appointment_form.label")}
      className="reveal mt-4 flex flex-col gap-4 rounded-xl border border-border bg-surface p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setPending(true);
        setError(null);
        try {
          const out = await portalApi.requestAppointment({
            recommendation_id: recommendationId ?? null,
            follow_up_id: followUpId ?? null,
            preferred_dates: date ? [date] : [],
            preferred_time_of_day: time || null,
            message: message.trim() || null,
          });
          setDone(out.confirmation ?? t("portal.appointment_form.sent"));
          setTimeout(onDone, 1500);
        } catch (err) {
          setError(apiErrorMessage(err));
        } finally {
          setPending(false);
        }
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <label className={labelClass}>
          {t("portal.appointment_form.date")}
          <input type="date" className={inputClass} value={date} min={new Date().toISOString().slice(0, 10)} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label className={labelClass}>
          {t("portal.appointment_form.time")}
          <select className={inputClass} value={time} onChange={(e) => setTime(e.target.value as TimeOfDay | "")}>
            <option value="">{t("portal.time.any")}</option>
            <option value="morning">{t("portal.time.morning")}</option>
            <option value="afternoon">{t("portal.time.afternoon")}</option>
            <option value="evening">{t("portal.time.evening")}</option>
          </select>
        </label>
      </div>
      <label className={labelClass}>
        {t("portal.appointment_form.message")}
        <textarea dir="auto" className={textareaClass} maxLength={1000} value={message} onChange={(e) => setMessage(e.target.value)} />
      </label>
      <FormError message={error} />
      <div className="flex gap-2">
        <button type="submit" className={buttonClass("primary")} disabled={pending}>
          {pending ? t("portal.sending") : t("portal.appointment_form.submit")}
        </button>
        <button type="button" className={buttonClass("secondary")} onClick={onCancel}>
          {t("portal.cancel")}
        </button>
      </div>
      <p className="text-xs text-faint">{t("portal.appointment_form.note")}</p>
    </form>
  );
}

function Appointments({ attempt, onChanged }: { attempt: number; onChanged: () => void }) {
  const appts = useResource(`p-appt|${attempt}`, "patients.read_self", (s) => portalApi.appointments(s), attempt);
  const refs = useResource(`p-ref|${attempt}`, "patients.read_self", (s) => portalApi.referrals(s), attempt);
  const [requesting, setRequesting] = useState(false);
  const { t } = useLocale();
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <Title title={t("portal.appointments.title")} subtitle={t("portal.appointments.subtitle")} />
        {!requesting && (
          <button type="button" className={buttonClass("primary")} onClick={() => setRequesting(true)}>
            <CalendarClock size={15} aria-hidden="true" /> {t("portal.appointments.request")}
          </button>
        )}
      </div>
      {requesting && <AppointmentRequestForm onDone={() => (setRequesting(false), onChanged())} onCancel={() => setRequesting(false)} />}
      <Plate title={t("portal.appointments.list")} flush>
        <ResourceView resource={appts} what={t("portal.what.appointments")}>
          {(a) =>
            a.items.length === 0 ? (
              <p className="px-5 py-4 text-sm text-muted">{t("portal.appointments.empty")}</p>
            ) : (
              <ul className="divide-y divide-border">
                {[...a.items].sort((x, y) => y.scheduled_datetime.localeCompare(x.scheduled_datetime)).map((x) => (
                  <AppointmentRow key={x.appointment_id} appt={x} onChanged={onChanged} />
                ))}
              </ul>
            )
          }
        </ResourceView>
      </Plate>
      <Plate title={t("portal.referrals.title")} flush>
        <ResourceView resource={refs} what={t("portal.what.referrals")}>
          {(r) =>
            r.items.length === 0 ? (
              <p className="px-5 py-4 text-sm text-muted">{t("portal.referrals.empty")}</p>
            ) : (
              <ul className="divide-y divide-border">
                {r.items.map((x) => (
                  <li key={x.referral_id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                    <span>
                      <span dir="auto" className="block text-foreground">{x.referral_target}</span>
                      <span className="text-xs text-faint">{t("portal.referrals.since", { date: x.trigger_date_display })}</span>
                    </span>
                    <span className="rounded-full border border-border px-2.5 py-0.5 text-xs text-foreground">{x.status_label}</span>
                  </li>
                ))}
              </ul>
            )
          }
        </ResourceView>
      </Plate>
    </>
  );
}

function AppointmentRow({ appt, onChanged }: { appt: PortalAppointmentOut; onChanged: () => void }) {
  const [action, setAction] = useState<"cancel" | "reschedule" | null>(null);
  const [message, setMessage] = useState("");
  const [state, setState] = useState<{ pending: boolean; error: string | null; done: string | null }>({ pending: false, error: null, done: null });
  const { t } = useLocale();
  return (
    <li className="px-5 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <span>
          <span className="block font-medium text-foreground">{appt.scheduled_display}</span>
          <span className="text-xs text-muted">{appt.appointment_type_label}</span>
        </span>
        <span className="flex items-center gap-2">
          <span className="rounded-full border border-border px-2.5 py-0.5 text-xs text-foreground">{appt.status_label}</span>
          {appt.can_request_change && !action && !state.done && (
            <>
              <button type="button" className={buttonClass("quiet")} onClick={() => setAction("reschedule")}>
                {t("portal.appointments.reschedule")}
              </button>
              <button type="button" className={buttonClass("quiet", "text-status-error")} onClick={() => setAction("cancel")}>
                {t("portal.appointments.cancel")}
              </button>
            </>
          )}
        </span>
      </div>
      {state.done && <div className="mt-3"><Confirmation>{state.done}</Confirmation></div>}
      {action && !state.done && (
        <form
          className="reveal mt-3 flex flex-col gap-3 rounded-lg border border-border bg-surface p-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setState({ pending: true, error: null, done: null });
            try {
              const out = await portalApi.requestAppointmentChange(appt.appointment_id, { action, message: message.trim() || null });
              setState({ pending: false, error: null, done: out.confirmation ?? t("portal.request_sent") });
              setAction(null);
              setTimeout(onChanged, 1500);
            } catch (err) {
              setState({ pending: false, error: apiErrorMessage(err), done: null });
            }
          }}
        >
          <label className={labelClass}>
            {action === "cancel" ? t("portal.appointments.cancel_reason") : t("portal.appointments.reschedule_times")}
            <textarea dir="auto" className={textareaClass} maxLength={1000} value={message} onChange={(e) => setMessage(e.target.value)} />
          </label>
          <FormError message={state.error} />
          <div className="flex gap-2">
            <button type="submit" className={buttonClass(action === "cancel" ? "warm" : "primary")} disabled={state.pending}>
              {state.pending ? t("portal.sending") : action === "cancel" ? t("portal.appointments.ask_cancel") : t("portal.appointments.ask_reschedule")}
            </button>
            <button type="button" className={buttonClass("secondary")} onClick={() => setAction(null)}>
              {t("portal.appointments.keep")}
            </button>
          </div>
        </form>
      )}
    </li>
  );
}

/* ── Messages (follow-ups) ────────────────────────────────────────────── */

const RESPONSES: { value: PatientResponse; label: MessageKey }[] = [
  { value: "will_book", label: "portal.response.will_book" },
  { value: "already_done", label: "portal.response.already_done" },
  { value: "need_help", label: "portal.response.need_help" },
  { value: "question", label: "portal.response.question" },
  { value: "not_interested", label: "portal.response.not_interested" },
];

function Messages({ attempt, onChanged }: { attempt: number; onChanged: () => void }) {
  const list = useResource(`p-fu|${attempt}`, "patients.read_self", (s) => portalApi.followUps(s), attempt);
  const [open, setOpen] = useState<string | null>(null);
  const { t } = useLocale();
  return (
    <>
      <Title title={t("portal.messages.title")} subtitle={t("portal.messages.subtitle")} />
      <ResourceView resource={list} what={t("portal.what.messages")}>
        {(l) =>
          l.items.length === 0 ? (
            <QuietEmpty title={t("portal.messages.empty.title")}>{t("portal.messages.empty.body")}</QuietEmpty>
          ) : (
            <ul className="flex flex-col gap-3">
              {l.items.map((f) => (
                <MessageCard key={f.follow_up_id} item={f} open={open === f.follow_up_id} onToggle={() => setOpen(open === f.follow_up_id ? null : f.follow_up_id)} onChanged={onChanged} />
              ))}
            </ul>
          )
        }
      </ResourceView>
    </>
  );
}

function MessageCard({ item, open, onToggle, onChanged }: { item: PortalFollowUpOut; open: boolean; onToggle: () => void; onChanged: () => void }) {
  const [v, setV] = useState(0);
  const detail = useResource(open ? `p-fud|${item.follow_up_id}|${v}` : null, "patients.read_self", (s) => portalApi.followUp(item.follow_up_id, s), v);
  const [response, setResponse] = useState<PatientResponse | "">("");
  const [message, setMessage] = useState("");
  const [state, setState] = useState<{ pending: boolean; error: string | null; done: string | null }>({ pending: false, error: null, done: null });
  const { t } = useLocale();
  return (
    <li className="rounded-xl border border-border bg-surface-raised">
      <button type="button" aria-expanded={open} onClick={onToggle} className="flex w-full items-start gap-3 px-5 py-4 text-start">
        <MessageSquare size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-accent" />
        <span className="min-w-0 flex-1">
          <span dir="auto" className="line-clamp-2 block text-sm text-foreground">{item.message}</span>
          <span className="mt-1.5 flex flex-wrap gap-x-3 text-xs text-faint">
            <span>{item.status_label}</span>
            {item.due_date_display && <span className={item.is_overdue ? "text-status-due" : undefined}>{t("portal.messages.due", { date: item.due_date_display })}</span>}
            <span>{item.updated_display}</span>
          </span>
          <span dir="auto" className="mt-1 block text-xs text-muted">{item.status_hint}</span>
        </span>
        <ChevronRight size={16} aria-hidden="true" className={cn("mt-1 text-faint transition-transform duration-200 rtl:-scale-x-100", open && "rotate-90")} />
      </button>
      {open && (
        <div className="reveal-fade border-t border-border px-5 py-4">
          <ResourceView resource={detail} what={t("portal.what.conversation")}>
            {(d) => (
              <ol className="flex flex-col gap-3">
                {d.history.map((h) => (
                  <li key={h.event_id} className={cn("max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm", h.from_care_team ? "self-start bg-surface-sunken" : "self-end bg-accent-soft")}>
                    <span className="block text-xs text-faint">
                      {h.from_care_team ? t("portal.messages.care_team") : t("portal.messages.you")} · {h.created_display}
                    </span>
                    <span dir="auto" className="text-foreground">{h.response_label ? `${h.response_label}${h.message ? ` — ${h.message}` : ""}` : (h.message ?? h.label)}</span>
                  </li>
                ))}
              </ol>
            )}
          </ResourceView>
          {state.done ? (
            <div className="mt-4"><Confirmation>{state.done}</Confirmation></div>
          ) : (
            !["completed", "cancelled"].includes(item.status) && (
              <form
                aria-label={t("portal.messages.reply")}
                className="mt-4 flex flex-col gap-3"
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (!response) return;
                  setState({ pending: true, error: null, done: null });
                  try {
                    const out = await portalApi.respond(item.follow_up_id, response, message.trim() || null);
                    setState({ pending: false, error: null, done: out.confirmation ?? t("portal.messages.reply_sent") });
                    setV((n) => n + 1);
                    setTimeout(onChanged, 1500);
                  } catch (err) {
                    setState({ pending: false, error: apiErrorMessage(err), done: null });
                  }
                }}
              >
                <fieldset>
                  <legend className="mb-2 text-xs font-medium text-muted">{t("portal.messages.your_reply")}</legend>
                  <div className="flex flex-wrap gap-2">
                    {RESPONSES.map((r) => (
                      <label
                        key={r.value}
                        className={cn(
                          "cursor-pointer rounded-full border px-3 py-1.5 text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)]",
                          response === r.value ? "border-accent bg-accent-soft font-medium text-foreground" : "border-border-strong text-muted hover:border-accent"
                        )}
                      >
                        <input type="radio" name={`resp-${item.follow_up_id}`} value={r.value} className="sr-only" checked={response === r.value} onChange={() => setResponse(r.value)} />
                        {t(r.label)}
                      </label>
                    ))}
                  </div>
                </fieldset>
                <textarea dir="auto" aria-label={t("portal.messages.message_label")} placeholder={t("portal.messages.message_placeholder")} className={textareaClass} maxLength={1000} value={message} onChange={(e) => setMessage(e.target.value)} />
                {response === "already_done" && (
                  <p className="text-xs text-faint">{t("portal.messages.already_done_note")}</p>
                )}
                <FormError message={state.error} />
                <button type="submit" className={buttonClass("primary", "self-start")} disabled={!response || state.pending}>
                  {state.pending ? t("portal.sending") : t("portal.messages.send_reply")}
                </button>
              </form>
            )
          )}
        </div>
      )}
    </li>
  );
}

/* ── Requests ─────────────────────────────────────────────────────────── */

function Requests({ attempt, onChanged }: { attempt: number; onChanged: () => void }) {
  const list = useResource(`p-req|${attempt}`, "patients.read_self", (s) => portalApi.requests(s), attempt);
  const [help, setHelp] = useState(false);
  const { t } = useLocale();
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <Title title={t("portal.requests.title")} subtitle={t("portal.requests.subtitle")} />
        {!help && (
          <button type="button" className={buttonClass("secondary")} onClick={() => setHelp(true)}>
            <LifeBuoy size={15} aria-hidden="true" /> {t("portal.requests.ask_help")}
          </button>
        )}
      </div>
      {help && <HelpForm onDone={() => (setHelp(false), onChanged())} onCancel={() => setHelp(false)} />}
      <ResourceView resource={list} what={t("portal.what.requests")}>
        {(l) =>
          l.items.length === 0 ? (
            <QuietEmpty title={t("portal.requests.empty")}>{t("portal.requests.empty_body")}</QuietEmpty>
          ) : (
            <Plate title={t("portal.requests.list")} flush>
              <ul className="divide-y divide-border">
                {l.items.map((r) => (
                  <RequestRow key={r.request_id} request={r} onChanged={onChanged} />
                ))}
              </ul>
            </Plate>
          )
        }
      </ResourceView>
    </>
  );
}

function RequestRow({ request: r, onChanged }: { request: PatientRequestOut; onChanged: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [state, setState] = useState<{ pending: boolean; error: string | null }>({ pending: false, error: null });
  const { t, rich } = useLocale();
  const withdraw = async () => {
    setState({ pending: true, error: null });
    try {
      await portalApi.cancelRequest(r.request_id);
      onChanged();
    } catch (err) {
      setState({ pending: false, error: apiErrorMessage(err) });
    }
  };
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 px-5 py-3.5 text-sm">
      <span className="min-w-0 flex-1">
        <span className="block font-medium text-foreground">
          {r.request_type_label}
          {r.change_action_label && ` · ${r.change_action_label}`}
        </span>
        {r.message && <span dir="auto" className="block text-muted">{r.message}</span>}
        {r.staff_response && (
          <span className="mt-1 block rounded-lg bg-surface-sunken px-3 py-2 text-foreground">
            {rich("portal.requests.care_team_reply", { reply: <span dir="auto">{r.staff_response}</span> })}
          </span>
        )}
        <span dir="auto" className="mt-1 block text-xs text-foreground">{r.status_hint}</span>
        <span className="mt-1 block text-xs text-faint">
          {t("portal.requests.sent", { date: r.created_display })}
          {r.updated_at !== r.created_at && ` · ${t("portal.requests.updated", { date: r.updated_display })}`}
        </span>
        <FormError message={state.error} />
      </span>
      <span className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-border px-2.5 py-0.5 text-xs text-foreground">{r.status_label}</span>
        {["submitted", "acknowledged"].includes(r.status) &&
          (confirming ? (
            <>
              <button type="button" className={buttonClass("warm")} disabled={state.pending} onClick={() => void withdraw()}>
                {t(state.pending ? "portal.requests.withdrawing" : "portal.requests.withdraw_yes")}
              </button>
              <button type="button" className={buttonClass("secondary")} onClick={() => setConfirming(false)}>
                {t("portal.requests.keep")}
              </button>
            </>
          ) : (
            <button type="button" className={buttonClass("quiet", "text-status-error")} onClick={() => setConfirming(true)}>
              {t("portal.requests.withdraw")}
            </button>
          ))}
      </span>
    </li>
  );
}

/* ── Health record ────────────────────────────────────────────────────── */

function HealthRecord({ attempt }: { attempt: number }) {
  const health = useResource(`p-health|${attempt}`, "patients.read_self", (s) => portalApi.healthSummary(s), attempt);
  const profile = useResource(`p-sum|${attempt}`, "patients.read_self", (s) => portalApi.summary(s), attempt);
  const { t } = useLocale();
  const channel = (c: string) => {
    const key = `portal.channel.${c}` as MessageKey;
    const label = t(key);
    return label === key ? c.replace(/_/g, " ") : label;
  };
  return (
    <>
      <Title title={t("portal.record.title")} subtitle={t("portal.record.subtitle")} />
      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Plate title={t("portal.record.about")}>
          <ResourceView resource={profile} what={t("portal.what.profile")}>
            {(p) => (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted">{t("portal.record.name")}</dt>
                <dd className="text-foreground">
                  {p.given_name} {p.family_name}
                </dd>
                <dt className="text-muted">{t("portal.record.dob")}</dt>
                <dd className="text-foreground">{p.date_of_birth_display ?? "—"}</dd>
                <dt className="text-muted">{t("language.label")}</dt>
                <dd className="text-foreground">{p.preferred_language === "ar" ? t("portal.record.lang_ar") : t("portal.record.lang_en")}</dd>
                <dt className="text-muted">{t("portal.record.contact")}</dt>
                <dd className="text-foreground">{channel(p.preferred_channel)}</dd>
                <dt className="text-muted">{t("portal.record.record")}</dt>
                <dd className="font-mono text-xs text-faint"><span className="ltr-value">{p.patient_id}</span></dd>
              </dl>
            )}
          </ResourceView>
        </Plate>
        <Plate title={t("portal.record.events")} flush>
          <ResourceView resource={health} what={t("portal.what.health")}>
            {(h) => (
              <>
                <ul className="flex flex-wrap gap-2 border-b border-border px-5 py-3">
                  {h.history.map((x) => (
                    <li key={x.programme} className="rounded-full bg-surface-sunken px-3 py-1 text-xs text-foreground">
                      {x.programme_label}: {x.status_label}
                    </li>
                  ))}
                </ul>
                {h.events.length === 0 ? (
                  <p className="px-5 py-4 text-sm text-muted">{t("portal.record.events_empty")}</p>
                ) : (
                  <ul className="divide-y divide-border">
                    {h.events.map((e, i) => (
                      <li key={i} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                        <span>
                          <span className="block text-foreground">{e.kind === "screening" ? t("portal.record.screening") : t("portal.record.well_child")}</span>
                          <span className="text-xs text-faint">{e.programme_label}</span>
                        </span>
                        <span className="text-end">
                          <span className="block text-foreground">{e.performed_date_display ?? t("portal.record.no_date")}</span>
                          <span className="text-xs text-muted">{e.status_label}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="px-5 py-3 text-xs text-faint">{h.disclaimer}</p>
              </>
            )}
          </ResourceView>
        </Plate>
      </div>
    </>
  );
}

/* ── Account linking ──────────────────────────────────────────────────── */

function LinkAccount({ onLinked }: { onLinked: () => void }) {
  const [code, setCode] = useState("");
  const [dob, setDob] = useState("");
  const [state, setState] = useState<{ pending: boolean; error: string | null }>({ pending: false, error: null });
  const { t } = useLocale();
  return (
    <div className="mx-auto max-w-md pt-10">
      <form
        aria-label={t("portal.link.label")}
        className="reveal rounded-2xl border border-border bg-surface-raised p-7 shadow-[var(--shadow-lift)]"
        onSubmit={async (e) => {
          e.preventDefault();
          setState({ pending: true, error: null });
          try {
            await portalApi.link(code.trim(), dob);
            onLinked();
          } catch (err) {
            setState({ pending: false, error: apiErrorMessage(err, t("portal.link.error")) });
          }
        }}
      >
        <h1 className="font-display text-[26px] font-medium text-foreground">{t("portal.link.title")}</h1>
        <p className="mt-1.5 text-sm text-muted">{t("portal.link.intro")}</p>
        <div className="mt-6 flex flex-col gap-4">
          <label className={labelClass}>
            {t("portal.link.code")}
            <input className={cn(inputClass, "font-mono uppercase")} value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" required />
          </label>
          <label className={labelClass}>
            {t("portal.record.dob")}
            <input type="date" className={inputClass} value={dob} onChange={(e) => setDob(e.target.value)} required />
          </label>
          <FormError message={state.error} />
          <button type="submit" className={buttonClass("primary", "w-full")} disabled={state.pending || code.trim().length < 4 || !dob}>
            {state.pending ? t("portal.link.pending") : t("portal.link.submit")}
          </button>
        </div>
      </form>
    </div>
  );
}
