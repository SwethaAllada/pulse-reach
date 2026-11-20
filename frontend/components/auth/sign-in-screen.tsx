"use client";

import { useState } from "react";
import { AlertCircle, ArrowRight, Eye, EyeOff, FileCheck2, FlaskConical, Info, ShieldCheck } from "lucide-react";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { buttonClass } from "@/components/ui/button-styles";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { LogoMark, LogoWordmark } from "@/components/shell/logo";

const REASON_TEXT = {
  none: null,
  expired: "Your session ended or was revoked. Sign in again to continue.",
  signed_out: "You have signed out.",
} as const;

function failureMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return err.serverMessage ?? "The e-mail or password is not correct.";
    if (err.status === 429) return err.serverMessage ?? "Too many attempts. Wait a few minutes and try again.";
    if (err.status === 422) return "Enter a valid e-mail address and password.";
    if (err.status === null) return err.message;
    return err.serverMessage ?? err.message;
  }
  return "Sign-in failed unexpectedly. Try again.";
}

/**
 * Sign-in for `AUTH_MODE=users`. Credentials go only to `POST /api/v1/auth/login`;
 * the browser keeps the returned opaque tokens for this tab (see lib/auth/session).
 */
export function SignInScreen({ reason }: { reason: "none" | "expired" | "signed_out" }) {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reveal, setReveal] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) return setError("Enter your e-mail and password.");
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch (err) {
      setError(failureMessage(err));
      setBusy(false);
    }
  };

  const notice = REASON_TEXT[reason];
  const field =
    "h-10 w-full rounded-lg border border-border-strong bg-surface-raised px-3 text-sm text-foreground placeholder:text-faint transition-[border-color,box-shadow] duration-200 hover:border-faint focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent-soft aria-invalid:border-status-error";

  return (
    <div className="relative flex min-h-screen flex-col">
      <header className="flex items-center justify-between px-6 py-5 sm:px-10">
        <LogoWordmark />
        <ThemeToggle />
      </header>

      <main className="flex flex-1 items-center justify-center px-6 pb-16">
        <div className="w-full max-w-[400px]">
          <section
            aria-label="Sign in"
            className="reveal rounded-2xl border border-border bg-surface-raised p-7 shadow-[var(--shadow-lift)] sm:p-8"
          >
            <LogoMark className="size-9" />
            <h2 className="mt-5 font-display text-[26px] font-medium tracking-[-0.015em] text-foreground">Sign in</h2>
            <p className="mt-1.5 text-sm text-muted">Use your PulseReach account to continue.</p>

            {notice && (
              <p role="status" className="mt-5 rounded-lg bg-highlight px-3 py-2 text-sm text-foreground">
                {notice}
              </p>
            )}

            <form onSubmit={submit} noValidate className="mt-6 flex flex-col gap-4">
              <label className="flex flex-col gap-1.5 text-[13px] font-medium text-foreground">
                E-mail
                <input
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className={field}
                  placeholder="name@organization.example"
                  aria-invalid={error !== null}
                />
              </label>
              <label className="flex flex-col gap-1.5 text-[13px] font-medium text-foreground">
                Password
                <span className="relative">
                  <input
                    type={reveal ? "text" : "password"}
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={`${field} pr-10`}
                    aria-invalid={error !== null}
                  />
                  <button
                    type="button"
                    onClick={() => setReveal((r) => !r)}
                    aria-label={reveal ? "Hide password" : "Show password"}
                    aria-pressed={reveal}
                    className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-lg text-faint transition-colors hover:text-foreground"
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
                    <span className="sr-only">Signing in…</span>
                  </>
                ) : (
                  <>
                    Sign in <ArrowRight size={16} aria-hidden="true" />
                  </>
                )}
              </button>
            </form>

            <p className="mt-6 flex gap-2 border-t border-border pt-5 text-xs leading-relaxed text-faint">
              <Info size={14} aria-hidden="true" className="mt-px shrink-0" />
              <span>
                Accounts are issued by your organization administrator. Care teams and patients sign in here; each account
                sees only what its role allows.
              </span>
            </p>
          </section>

          <ul className="reveal mt-6 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-xs text-faint [--i:2]">
            <li className="flex items-center gap-1.5">
              <ShieldCheck size={13} aria-hidden="true" className="text-accent" /> Role-based access
            </li>
            <li className="flex items-center gap-1.5">
              <FileCheck2 size={13} aria-hidden="true" className="text-accent" /> Every access audited
            </li>
            <li className="flex items-center gap-1.5">
              <FlaskConical size={13} aria-hidden="true" className="text-warm-text" /> Synthetic data only
            </li>
          </ul>
        </div>
      </main>
    </div>
  );
}
