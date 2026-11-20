"use client";

import { useState } from "react";
import { AlertCircle, ArrowRight, Eye, EyeOff, FileCheck2, FlaskConical, Info, ShieldCheck } from "lucide-react";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { buttonClass } from "@/components/ui/button-styles";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { LogoMark, LogoWordmark } from "@/components/shell/logo";
import { LanguageSwitcher } from "@/components/i18n/language-switcher";
import { t, type MessageKey } from "@/lib/i18n/translate";
import { useT } from "@/lib/i18n/use-locale";

const REASON_TEXT: Record<"none" | "expired" | "signed_out", MessageKey | null> = {
  none: null,
  expired: "auth.reason_expired",
  signed_out: "auth.reason_signed_out",
};

/** Server messages are already localized by the backend (`Accept-Language`). */
function failureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return err.serverMessage ?? t("auth.error_credentials");
    if (err.status === 429) return err.serverMessage ?? t("auth.error_rate_limited");
    if (err.status === 422) return t("auth.error_invalid_input");
    if (err.status === null) return err.message;
    return err.serverMessage ?? err.message;
  }
  return t("auth.error_unexpected");
}

/**
 * Sign-in for `AUTH_MODE=users`. Credentials go only to `POST /api/v1/auth/login`;
 * the browser keeps the returned opaque tokens for this tab (see lib/auth/session).
 */
export function SignInScreen({ reason }: { reason: "none" | "expired" | "signed_out" }) {
  const { signIn } = useAuth();
  const tr = useT();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reveal, setReveal] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) return setError(tr("auth.error_required"));
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch (err) {
      setError(failureMessage(err));
      setBusy(false);
    }
  };

  const noticeKey = REASON_TEXT[reason];
  const notice = noticeKey && tr(noticeKey);
  const field =
    "h-10 w-full rounded-lg border border-border-strong bg-surface-raised px-3 text-sm text-foreground placeholder:text-faint transition-[border-color,box-shadow] duration-200 hover:border-faint focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent-soft aria-invalid:border-status-error";

  return (
    <div className="relative flex min-h-screen flex-col">
      <header className="flex items-center justify-between px-6 py-5 sm:px-10">
        <LogoWordmark />
        <div className="flex items-center gap-2">
          <LanguageSwitcher />
          <ThemeToggle />
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-6 pb-16">
        <div className="w-full max-w-[400px]">
          <section
            aria-label={tr("auth.sign_in")}
            className="reveal rounded-2xl border border-border bg-surface-raised p-7 shadow-[var(--shadow-lift)] sm:p-8"
          >
            <LogoMark className="size-9" />
            <h2 className="mt-5 font-display text-[26px] font-medium tracking-[-0.015em] text-foreground">{tr("auth.sign_in")}</h2>
            <p className="mt-1.5 text-sm text-muted">{tr("auth.sign_in_subtitle")}</p>

            {notice && (
              <p role="status" className="mt-5 rounded-lg bg-highlight px-3 py-2 text-sm text-foreground">
                {notice}
              </p>
            )}

            <form onSubmit={submit} noValidate className="mt-6 flex flex-col gap-4">
              <label className="flex flex-col gap-1.5 text-[13px] font-medium text-foreground">
                {tr("auth.email")}
                <input
                  type="email"
                  dir="ltr"
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className={field}
                  placeholder={tr("auth.email_placeholder")}
                  aria-invalid={error !== null}
                />
              </label>
              <label className="flex flex-col gap-1.5 text-[13px] font-medium text-foreground">
                {tr("auth.password")}
                <span className="relative">
                  <input
                    type={reveal ? "text" : "password"}
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={`${field} pe-10`}
                    aria-invalid={error !== null}
                  />
                  <button
                    type="button"
                    onClick={() => setReveal((r) => !r)}
                    aria-label={tr(reveal ? "auth.hide_password" : "auth.show_password")}
                    aria-pressed={reveal}
                    className="absolute inset-y-0 end-0 flex w-10 items-center justify-center rounded-e-lg text-faint transition-colors hover:text-foreground"
                  >
                    {reveal ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
                  </button>
                </span>
              </label>

              <div aria-live="assertive" className="empty:hidden">
                {error && (
                  <p role="alert" className="reveal flex items-start gap-2 rounded-lg bg-[color-mix(in_srgb,var(--danger)_10%,transparent)] px-3 py-2 text-sm text-status-error">
                    <AlertCircle size={15} aria-hidden="true" className="mt-0.5 shrink-0" />
                    {error}
                  </p>
                )}
              </div>

              <button type="submit" disabled={busy} className={buttonClass("primary", "mt-1 w-full")}>
                {busy ? (
                  <>
                    <span className="progress-track h-1 w-16 rounded-full bg-[color-mix(in_srgb,var(--on-action)_20%,transparent)] text-on-action" />
                    <span className="sr-only">{tr("auth.signing_in")}</span>
                  </>
                ) : (
                  <>
                    {tr("auth.sign_in")} <ArrowRight size={16} aria-hidden="true" className="rtl:-scale-x-100" />
                  </>
                )}
              </button>
            </form>

            <p className="mt-6 flex gap-2 border-t border-border pt-5 text-xs leading-relaxed text-faint">
              <Info size={14} aria-hidden="true" className="mt-px shrink-0" />
              <span>{tr("auth.accounts_note")}</span>
            </p>
          </section>

          <ul className="reveal mt-6 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-xs text-faint [--i:2]">
            <li className="flex items-center gap-1.5">
              <ShieldCheck size={13} aria-hidden="true" className="text-accent" /> {tr("auth.badge_rbac")}
            </li>
            <li className="flex items-center gap-1.5">
              <FileCheck2 size={13} aria-hidden="true" className="text-accent" /> {tr("auth.badge_audited")}
            </li>
            <li className="flex items-center gap-1.5">
              <FlaskConical size={13} aria-hidden="true" className="text-warm-text" /> {tr("auth.badge_synthetic")}
            </li>
          </ul>
        </div>
      </main>
    </div>
  );
}
