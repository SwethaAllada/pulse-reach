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
  Sparkles,
} from "lucide-react";
import { portalApi, apiErrorMessage } from "@/lib/api/client";
import { useResource, type Resource } from "@/lib/api/resource";
import type { AssistantTopic, PatientAssistantOut, PatientRequestOut, PatientResponse, PortalAppointmentOut, PortalFollowUpOut, RecommendationOut, TimeOfDay } from "@/lib/api/portal-types";
import { useAuth } from "@/lib/auth/auth-context";
import { LogoMark, LogoWordmark } from "@/components/shell/logo";
import { SyntheticBanner } from "@/components/shell/synthetic-banner";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { Plate } from "@/components/ui/plate";
import { KpiCard } from "@/components/ui/figure";
import { buttonClass } from "@/components/ui/button-styles";
import { ResourceView } from "@/components/programmes/resource-state";
import { Confirmation, FormError, QuietEmpty, inputClass, labelClass, textareaClass } from "@/components/coordination/primitives";
import { cn } from "@/lib/cn";

type View = "home" | "care" | "appointments" | "messages" | "requests" | "record";

const VIEWS: { id: View; label: string; icon: typeof Home }[] = [
  { id: "home", label: "Overview", icon: Home },
  { id: "care", label: "Recommended care", icon: ClipboardCheck },
  { id: "appointments", label: "Appointments", icon: CalendarClock },
  { id: "messages", label: "Messages", icon: MessageSquare },
  { id: "requests", label: "My requests", icon: Inbox },
  { id: "record", label: "Health record", icon: FileHeart },
];

/**
 * The patient portal: a separate experience for PATIENT accounts. Every call goes to
 * `/portal/*`, where the backend derives the patient from the verified account link; staff
 * endpoints are never called with a patient session.
 */
export function PatientPortal() {
  const { state, signOut, retry } = useAuth();
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
            <p className="text-[11px] text-faint">Patient portal</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden text-sm text-muted sm:inline">{me?.user.full_name}</span>
            <ThemeToggle />
            <button type="button" className={buttonClass("secondary")} onClick={() => void signOut()}>
              <LogOut size={14} aria-hidden="true" /> Sign out
            </button>
          </div>
        </div>
        {me?.patient_linked && (
          <nav aria-label="Portal" className="mx-auto flex max-w-[1120px] gap-1 overflow-x-auto px-4 sm:px-6">
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
                {label}
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
        PulseReach never sends e-mail or SMS. Information here is synthetic and not medical advice.
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
  const summary = useResource(`p-sum|${attempt}`, "patients.read_self", (s) => portalApi.summary(s), attempt);
  const recs = useResource(`p-rec|active|${attempt}`, "patients.read_self", (s) => portalApi.recommendations("active", s), attempt);
  const appts = useResource(`p-appt|${attempt}`, "patients.read_self", (s) => portalApi.appointments(s), attempt);
  const name = summary.status === "ready" ? summary.data.given_name : "";
  const next = appts.status === "ready" ? appts.data.items.filter((a) => ["scheduled", "rescheduled"].includes(a.status)).sort((a, b) => a.scheduled_datetime.localeCompare(b.scheduled_datetime))[0] : undefined;

  return (
    <>
      <Title title={name ? `Hello, ${name}` : "Your health overview"} subtitle="Recommended preventive care, appointments and messages from your care team." />
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="Recommended care" value={num(summary, (d) => d.open_recommendations)} note="open recommendations" onClick={() => onNavigate("care")} />
        <Tile label="Upcoming appointments" value={num(summary, (d) => d.upcoming_appointments)} note="scheduled visits" onClick={() => onNavigate("appointments")} />
        <Tile label="Awaiting your reply" value={num(summary, (d) => d.awaiting_your_reply)} note="messages from your care team" onClick={() => onNavigate("messages")} />
        <Tile label="Open requests" value={num(summary, (d) => d.open_requests)} note="being handled" onClick={() => onNavigate("requests")} />
      </dl>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Plate title="What to do next" description="Care your programme recommends, based on your recorded history." flush>
          <ResourceView resource={recs} what="Recommendations">
            {(r) =>
              r.items.length === 0 ? (
                <p className="px-5 py-4 text-sm text-muted">You are up to date — nothing is recommended right now.</p>
              ) : (
                <ul className="divide-y divide-border">
                  {r.items.slice(0, 4).map((x) => (
                    <li key={x.recommendation_id}>
                      <button type="button" onClick={() => onNavigate("care")} className="group flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors hover:bg-hover">
                        <HeartPulse size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-warm-text" />
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium text-foreground">{x.title}</span>
                          <span className="block text-xs text-muted">
                            {x.programme_label} · {x.next_step_text}
                          </span>
                        </span>
                        <ChevronRight size={15} aria-hidden="true" className="mt-0.5 text-faint group-hover:text-foreground" />
                      </button>
                    </li>
                  ))}
                </ul>
              )
            }
          </ResourceView>
        </Plate>
        <Plate title="Next appointment">
          <ResourceView resource={appts} what="Appointments">
            {() =>
              next ? (
                <div>
                  <p className="text-lg font-semibold text-foreground">{next.scheduled_display}</p>
                  <p className="mt-1 text-sm text-muted">
                    {next.appointment_type_label} · {next.status_label}
                  </p>
                  <button type="button" className={buttonClass("secondary", "mt-4")} onClick={() => onNavigate("appointments")}>
                    Manage appointments
                  </button>
                </div>
              ) : (
                <div>
                  <p className="text-sm text-muted">No appointment is scheduled.</p>
                  <button type="button" className={buttonClass("primary", "mt-4")} onClick={() => onNavigate("appointments")}>
                    Request an appointment
                  </button>
                </div>
              )
            }
          </ResourceView>
        </Plate>
      </div>
    </>
  );
}

function Tile({ label, value, note, onClick }: { label: string; value: React.ReactNode; note: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="text-left transition-transform duration-200 hover:-translate-y-0.5">
      <KpiCard label={label} value={value} note={note} className="h-full hover:border-accent" />
    </button>
  );
}

/* ── Recommended care ─────────────────────────────────────────────────── */

function Recommendations({ attempt, onChanged }: { attempt: number; onChanged: () => void }) {
  const [status, setStatus] = useState<"active" | "all">("active");
  const [open, setOpen] = useState<string | null>(null);
  const recs = useResource(`p-rec|${status}|${attempt}`, "patients.read_self", (s) => portalApi.recommendations(status, s), attempt);
  return (
    <>
      <Title title="Recommended care" subtitle="Preventive care recommended for you. Only your care team can mark care as complete." />
      <div className="flex gap-2">
        {(["active", "all"] as const).map((s) => (
          <button key={s} type="button" aria-pressed={status === s} onClick={() => setStatus(s)} className={cn(buttonClass("secondary"), status === s && "border-accent bg-accent-soft")}>
            {s === "active" ? "Open" : "All, including closed"}
          </button>
        ))}
      </div>
      <ResourceView resource={recs} what="Recommendations">
        {(r) =>
          r.items.length === 0 ? (
            <QuietEmpty title="Nothing recommended">You are up to date.</QuietEmpty>
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
  return (
    <li className="rounded-xl border border-border bg-surface-raised">
      <button type="button" aria-expanded={open} onClick={onToggle} className="flex w-full items-start gap-3 px-5 py-4 text-left">
        <HeartPulse size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-warm-text" />
        <span className="min-w-0 flex-1">
          <span dir="auto" className="block font-medium text-foreground">{rec.title}</span>
          <span dir="auto" className="mt-0.5 block text-sm text-muted">{rec.description}</span>
          <span className="mt-2 flex flex-wrap gap-x-3 text-xs text-faint">
            <span>{rec.programme_label}</span>
            <span>Identified {rec.identified_date_display}</span>
            <span>{rec.status_label}</span>
          </span>
        </span>
        <ChevronRight size={16} aria-hidden="true" className={cn("mt-1 text-faint transition-transform duration-200", open && "rotate-90")} />
      </button>
      {open && (
        <div className="reveal-fade border-t border-border px-5 py-4">
          <ResourceView resource={detail} what="Details">
            {(d) => (
              <div className="grid gap-5 md:grid-cols-2">
                <div>
                  <h3 className="text-xs font-medium text-muted">Why this is recommended</h3>
                  <ul dir="auto" className="mt-2 list-disc space-y-1 ps-5 text-sm text-foreground">
                    {d.evidence.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                  <p dir="auto" className="mt-3 rounded-lg bg-accent-soft px-3 py-2 text-sm text-foreground">
                    <span className="font-medium">Next step:</span> {d.next_step_text}
                  </p>
                </div>
                <div>
                  <h3 className="text-xs font-medium text-muted">History</h3>
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
                <CalendarClock size={15} aria-hidden="true" /> Request an appointment for this
              </button>
            ))}
        </div>
      )}
    </li>
  );
}

/* ── Recommendation assistant ─────────────────────────────────────────── */

const TOPICS: { id: AssistantTopic; label: string }[] = [
  { id: "why", label: "Why is this recommended?" },
  { id: "next_steps", label: "What happens next?" },
  { id: "prepare_questions", label: "Questions for my clinician" },
  { id: "appointments", label: "Appointments and follow-up" },
];

/**
 * Plain-language help on fixed topics about this recommendation. The backend answers from the
 * patient's own portal facts (a guarded AI answer when enabled, otherwise the standard
 * explanation); it never changes, books or sends anything.
 */
function RecommendationAssistant({ recommendationId }: { recommendationId: string }) {
  const [topic, setTopic] = useState<AssistantTopic | null>(null);
  const [state, setState] = useState<{ pending: boolean; error: string | null; data: PatientAssistantOut | null }>({ pending: false, error: null, data: null });
  const [asking, setAsking] = useState(false);
  const ask = async (t: AssistantTopic) => {
    setTopic(t);
    setState({ pending: true, error: null, data: null });
    try {
      setState({ pending: false, error: null, data: await portalApi.assistant(recommendationId, t) });
    } catch (err) {
      setState({ pending: false, error: apiErrorMessage(err), data: null });
    }
  };
  const d = state.data;
  return (
    <section aria-label="Understand this recommendation" className="mt-5 rounded-xl border border-border bg-surface p-4">
      <h3 className="flex items-center gap-2 text-sm font-medium text-foreground">
        <Sparkles size={15} aria-hidden="true" className="text-accent" /> Understand this recommendation
      </h3>
      <div role="group" aria-label="Choose a topic" className="mt-3 flex flex-wrap gap-2">
        {TOPICS.map((x) => (
          <button key={x.id} type="button" aria-pressed={topic === x.id} disabled={state.pending} onClick={() => void ask(x.id)} className={cn(buttonClass("secondary"), topic === x.id && "border-accent bg-accent-soft")}>
            {x.label}
          </button>
        ))}
      </div>
      <div aria-live="polite" className="mt-3">
        {state.pending && <p className="skeleton h-16 rounded-lg" aria-label="Preparing an answer" />}
        {state.error && (
          <div className="flex flex-wrap items-center gap-3">
            <FormError message={state.error} />
            {topic && (
              <button type="button" className={buttonClass("secondary")} onClick={() => void ask(topic)}>
                Try again
              </button>
            )}
          </div>
        )}
        {d && (
          <div dir={d.direction} lang={d.locale} className="reveal-fade flex flex-col gap-2 text-sm">
            <h4 className="font-medium text-foreground">{d.topic_label}</h4>
            {d.topic === "prepare_questions" ? (
              <ul className="list-disc space-y-1 ps-5 text-foreground">{d.answer.map((a, i) => <li key={i}>{a}</li>)}</ul>
            ) : (
              d.answer.map((a, i) => <p key={i} className="text-foreground">{a}</p>)
            )}
            <p className="rounded-lg bg-surface-sunken px-3 py-2 text-foreground">{d.escalation}</p>
            <p className="text-xs text-faint">{d.source_note}</p>
          </div>
        )}
      </div>
      {d &&
        (asking ? (
          <HelpForm initial={`${d.topic_label}: `} onDone={() => setAsking(false)} onCancel={() => setAsking(false)} />
        ) : (
          <button type="button" className={buttonClass("primary", "mt-3")} onClick={() => setAsking(true)}>
            <LifeBuoy size={15} aria-hidden="true" /> Ask your care team
          </button>
        ))}
    </section>
  );
}

function HelpForm({ initial = "", onDone, onCancel }: { initial?: string; onDone: () => void; onCancel: () => void }) {
  const [msg, setMsg] = useState(initial);
  const [state, setState] = useState<{ pending: boolean; error: string | null; done: string | null }>({ pending: false, error: null, done: null });
  if (state.done) return <div className="mt-3"><Confirmation>{state.done}</Confirmation></div>;
  return (
    <form
      aria-label="Ask for help"
      className="reveal mt-3 flex flex-col gap-3 rounded-xl border border-border bg-surface-raised p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setState({ pending: true, error: null, done: null });
        try {
          const out = await portalApi.requestAssistance(msg.trim(), null);
          setState({ pending: false, error: null, done: out.confirmation ?? "Your request was sent to your care team." });
          setTimeout(onDone, 1500);
        } catch (err) {
          setState({ pending: false, error: apiErrorMessage(err), done: null });
        }
      }}
    >
      <label className={labelClass}>
        How can your care team help?
        <textarea dir="auto" className={textareaClass} maxLength={1000} value={msg} onChange={(e) => setMsg(e.target.value)} required />
      </label>
      <FormError message={state.error} />
      <div className="flex gap-2">
        <button type="submit" className={buttonClass("primary")} disabled={!msg.trim() || state.pending}>
          {state.pending ? "Sending…" : "Send"}
        </button>
        <button type="button" className={buttonClass("secondary")} onClick={onCancel}>
          Cancel
        </button>
      </div>
      <p className="text-xs text-faint">Your care team replies here in the portal. PulseReach does not send e-mail or SMS.</p>
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
  if (done) return <div className="mt-4"><Confirmation>{done}</Confirmation></div>;
  return (
    <form
      aria-label="Appointment request"
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
          setDone(out.confirmation ?? "Your request was sent to your care team. They will contact you to confirm a time.");
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
          Preferred date (optional)
          <input type="date" className={inputClass} value={date} min={new Date().toISOString().slice(0, 10)} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label className={labelClass}>
          Preferred time of day
          <select className={inputClass} value={time} onChange={(e) => setTime(e.target.value as TimeOfDay | "")}>
            <option value="">No preference</option>
            <option value="morning">Morning</option>
            <option value="afternoon">Afternoon</option>
            <option value="evening">Evening</option>
          </select>
        </label>
      </div>
      <label className={labelClass}>
        Message to your care team (optional)
        <textarea dir="auto" className={textareaClass} maxLength={1000} value={message} onChange={(e) => setMessage(e.target.value)} />
      </label>
      <FormError message={error} />
      <div className="flex gap-2">
        <button type="submit" className={buttonClass("primary")} disabled={pending}>
          {pending ? "Sending…" : "Send request"}
        </button>
        <button type="button" className={buttonClass("secondary")} onClick={onCancel}>
          Cancel
        </button>
      </div>
      <p className="text-xs text-faint">A request is not a booking: your care team confirms the time with you.</p>
    </form>
  );
}

function Appointments({ attempt, onChanged }: { attempt: number; onChanged: () => void }) {
  const appts = useResource(`p-appt|${attempt}`, "patients.read_self", (s) => portalApi.appointments(s), attempt);
  const refs = useResource(`p-ref|${attempt}`, "patients.read_self", (s) => portalApi.referrals(s), attempt);
  const [requesting, setRequesting] = useState(false);
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <Title title="Appointments" subtitle="Visits recorded by your care team, and referrals made for you." />
        {!requesting && (
          <button type="button" className={buttonClass("primary")} onClick={() => setRequesting(true)}>
            <CalendarClock size={15} aria-hidden="true" /> Request an appointment
          </button>
        )}
      </div>
      {requesting && <AppointmentRequestForm onDone={() => (setRequesting(false), onChanged())} onCancel={() => setRequesting(false)} />}
      <Plate title="Your appointments" flush>
        <ResourceView resource={appts} what="Appointments">
          {(a) =>
            a.items.length === 0 ? (
              <p className="px-5 py-4 text-sm text-muted">No appointments are recorded.</p>
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
      <Plate title="Referrals" flush>
        <ResourceView resource={refs} what="Referrals">
          {(r) =>
            r.items.length === 0 ? (
              <p className="px-5 py-4 text-sm text-muted">No referrals.</p>
            ) : (
              <ul className="divide-y divide-border">
                {r.items.map((x) => (
                  <li key={x.referral_id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                    <span>
                      <span dir="auto" className="block text-foreground">{x.referral_target}</span>
                      <span className="text-xs text-faint">Since {x.trigger_date_display}</span>
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
                Reschedule
              </button>
              <button type="button" className={buttonClass("quiet", "text-status-error")} onClick={() => setAction("cancel")}>
                Cancel
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
              setState({ pending: false, error: null, done: out.confirmation ?? "Your request was sent to your care team." });
              setAction(null);
              setTimeout(onChanged, 1500);
            } catch (err) {
              setState({ pending: false, error: apiErrorMessage(err), done: null });
            }
          }}
        >
          <label className={labelClass}>
            {action === "cancel" ? "Reason for cancelling (optional)" : "Which times suit you better? (optional)"}
            <textarea dir="auto" className={textareaClass} maxLength={1000} value={message} onChange={(e) => setMessage(e.target.value)} />
          </label>
          <FormError message={state.error} />
          <div className="flex gap-2">
            <button type="submit" className={buttonClass(action === "cancel" ? "warm" : "primary")} disabled={state.pending}>
              {state.pending ? "Sending…" : action === "cancel" ? "Ask to cancel" : "Ask to reschedule"}
            </button>
            <button type="button" className={buttonClass("secondary")} onClick={() => setAction(null)}>
              Keep appointment
            </button>
          </div>
        </form>
      )}
    </li>
  );
}

/* ── Messages (follow-ups) ────────────────────────────────────────────── */

const RESPONSES: { value: PatientResponse; label: string }[] = [
  { value: "will_book", label: "I will book it" },
  { value: "already_done", label: "I already had it done" },
  { value: "need_help", label: "I need help" },
  { value: "question", label: "I have a question" },
  { value: "not_interested", label: "Not right now" },
];

function Messages({ attempt, onChanged }: { attempt: number; onChanged: () => void }) {
  const list = useResource(`p-fu|${attempt}`, "patients.read_self", (s) => portalApi.followUps(s), attempt);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <Title title="Messages" subtitle="Messages from your care team. Reply to let them know how you would like to continue." />
      <ResourceView resource={list} what="Messages">
        {(l) =>
          l.items.length === 0 ? (
            <QuietEmpty title="No messages">Your care team has not sent you a message.</QuietEmpty>
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
  return (
    <li className="rounded-xl border border-border bg-surface-raised">
      <button type="button" aria-expanded={open} onClick={onToggle} className="flex w-full items-start gap-3 px-5 py-4 text-left">
        <MessageSquare size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-accent" />
        <span className="min-w-0 flex-1">
          <span dir="auto" className="line-clamp-2 block text-sm text-foreground">{item.message}</span>
          <span className="mt-1.5 flex flex-wrap gap-x-3 text-xs text-faint">
            <span>{item.status_label}</span>
            {item.due_date_display && <span className={item.is_overdue ? "text-status-due" : undefined}>Due {item.due_date_display}</span>}
            <span>{item.updated_display}</span>
          </span>
          <span dir="auto" className="mt-1 block text-xs text-muted">{item.status_hint}</span>
        </span>
        <ChevronRight size={16} aria-hidden="true" className={cn("mt-1 text-faint transition-transform duration-200", open && "rotate-90")} />
      </button>
      {open && (
        <div className="reveal-fade border-t border-border px-5 py-4">
          <ResourceView resource={detail} what="Conversation">
            {(d) => (
              <ol className="flex flex-col gap-3">
                {d.history.map((h) => (
                  <li key={h.event_id} className={cn("max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm", h.from_care_team ? "self-start bg-surface-sunken" : "self-end bg-accent-soft")}>
                    <span className="block text-xs text-faint">
                      {h.from_care_team ? "Care team" : "You"} · {h.created_display}
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
                aria-label="Reply"
                className="mt-4 flex flex-col gap-3"
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (!response) return;
                  setState({ pending: true, error: null, done: null });
                  try {
                    const out = await portalApi.respond(item.follow_up_id, response, message.trim() || null);
                    setState({ pending: false, error: null, done: out.confirmation ?? "Your reply was sent to your care team." });
                    setV((n) => n + 1);
                    setTimeout(onChanged, 1500);
                  } catch (err) {
                    setState({ pending: false, error: apiErrorMessage(err), done: null });
                  }
                }}
              >
                <fieldset>
                  <legend className="mb-2 text-xs font-medium text-muted">Your reply</legend>
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
                        {r.label}
                      </label>
                    ))}
                  </div>
                </fieldset>
                <textarea dir="auto" aria-label="Message (optional)" placeholder="Add a message (optional)" className={textareaClass} maxLength={1000} value={message} onChange={(e) => setMessage(e.target.value)} />
                {response === "already_done" && (
                  <p className="text-xs text-faint">Thanks — your care team will verify this. A report does not close a recommendation on its own.</p>
                )}
                <FormError message={state.error} />
                <button type="submit" className={buttonClass("primary", "self-start")} disabled={!response || state.pending}>
                  {state.pending ? "Sending…" : "Send reply"}
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
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <Title title="My requests" subtitle="Appointment, change and help requests you sent, and your care team’s replies." />
        {!help && (
          <button type="button" className={buttonClass("secondary")} onClick={() => setHelp(true)}>
            <LifeBuoy size={15} aria-hidden="true" /> Ask for help
          </button>
        )}
      </div>
      {help && <HelpForm onDone={() => (setHelp(false), onChanged())} onCancel={() => setHelp(false)} />}
      <ResourceView resource={list} what="Requests">
        {(l) =>
          l.items.length === 0 ? (
            <QuietEmpty title="No requests yet">Requests you send to your care team, and their replies, appear here.</QuietEmpty>
          ) : (
            <Plate title="Requests" flush>
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
            Care team: <span dir="auto">{r.staff_response}</span>
          </span>
        )}
        <span dir="auto" className="mt-1 block text-xs text-foreground">{r.status_hint}</span>
        <span className="mt-1 block text-xs text-faint">
          Sent {r.created_display}
          {r.updated_at !== r.created_at && ` · Updated ${r.updated_display}`}
        </span>
        <FormError message={state.error} />
      </span>
      <span className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-border px-2.5 py-0.5 text-xs text-foreground">{r.status_label}</span>
        {["submitted", "acknowledged"].includes(r.status) &&
          (confirming ? (
            <>
              <button type="button" className={buttonClass("warm")} disabled={state.pending} onClick={() => void withdraw()}>
                {state.pending ? "Withdrawing…" : "Yes, withdraw"}
              </button>
              <button type="button" className={buttonClass("secondary")} onClick={() => setConfirming(false)}>
                Keep request
              </button>
            </>
          ) : (
            <button type="button" className={buttonClass("quiet", "text-status-error")} onClick={() => setConfirming(true)}>
              Withdraw
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
  return (
    <>
      <Title title="Health record" subtitle="Your programmes and recorded screenings and visits." />
      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Plate title="About you">
          <ResourceView resource={profile} what="Profile">
            {(p) => (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted">Name</dt>
                <dd className="text-foreground">
                  {p.given_name} {p.family_name}
                </dd>
                <dt className="text-muted">Date of birth</dt>
                <dd className="text-foreground">{p.date_of_birth_display ?? "—"}</dd>
                <dt className="text-muted">Language</dt>
                <dd className="text-foreground">{p.preferred_language === "ar" ? "Arabic" : "English"}</dd>
                <dt className="text-muted">Contact by</dt>
                <dd className="text-foreground">{p.preferred_channel.replace(/_/g, " ")}</dd>
                <dt className="text-muted">Record</dt>
                <dd className="font-mono text-xs text-faint">{p.patient_id}</dd>
              </dl>
            )}
          </ResourceView>
        </Plate>
        <Plate title="Screenings and visits" flush>
          <ResourceView resource={health} what="Health summary">
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
                  <p className="px-5 py-4 text-sm text-muted">No screenings or visits are recorded.</p>
                ) : (
                  <ul className="divide-y divide-border">
                    {h.events.map((e, i) => (
                      <li key={i} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                        <span>
                          <span className="block text-foreground">{e.kind === "screening" ? "Screening" : "Well-child visit"}</span>
                          <span className="text-xs text-faint">{e.programme_label}</span>
                        </span>
                        <span className="text-right">
                          <span className="block text-foreground">{e.performed_date_display ?? "Date not recorded"}</span>
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
  return (
    <div className="mx-auto max-w-md pt-10">
      <form
        aria-label="Link your record"
        className="reveal rounded-2xl border border-border bg-surface-raised p-7 shadow-[var(--shadow-lift)]"
        onSubmit={async (e) => {
          e.preventDefault();
          setState({ pending: true, error: null });
          try {
            await portalApi.link(code.trim(), dob);
            onLinked();
          } catch (err) {
            setState({ pending: false, error: apiErrorMessage(err, "The code or date of birth did not match.") });
          }
        }}
      >
        <h1 className="font-display text-[26px] font-medium text-foreground">Link your health record</h1>
        <p className="mt-1.5 text-sm text-muted">Enter the invitation code your care team gave you and your date of birth.</p>
        <div className="mt-6 flex flex-col gap-4">
          <label className={labelClass}>
            Invitation code
            <input className={cn(inputClass, "font-mono uppercase")} value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" required />
          </label>
          <label className={labelClass}>
            Date of birth
            <input type="date" className={inputClass} value={dob} onChange={(e) => setDob(e.target.value)} required />
          </label>
          <FormError message={state.error} />
          <button type="submit" className={buttonClass("primary", "w-full")} disabled={state.pending || code.trim().length < 4 || !dob}>
            {state.pending ? "Linking…" : "Link my record"}
          </button>
        </div>
      </form>
    </div>
  );
}
