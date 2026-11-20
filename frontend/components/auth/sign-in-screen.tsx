"use client";

import { useState } from "react";
import { ArrowRight, Info } from "lucide-react";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { buttonClass } from "@/components/ui/button-styles";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { LogoMark, LogoWordmark } from "@/components/shell/logo";
import { AtlasOrnament } from "./atlas-ornament";

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
    "h-11 w-full rounded-xl border border-border-strong bg-surface-raised px-3.5 text-[15px] text-foreground placeholder:text-faint transition-colors hover:border-faint focus:border-accent focus:outline-none";

  return (
    <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <section
        aria-label="About PulseReach"
        className="relative flex flex-col justify-between overflow-hidden bg-ink px-6 py-8 sm:px-10 lg:px-14 lg:py-12"
      >
        <div className="flex items-center gap-3">
          <LogoMark />
          <span className="font-display text-xl font-medium tracking-[-0.02em] text-ink-text">
            Pulse<span className="italic text-ink-accent">Reach</span>
          </span>
        </div>
        <AtlasOrnament className="pointer-events-none absolute -right-56 top-1/2 hidden w-[620px] -translate-y-1/2 opacity-70 lg:block xl:-right-40" />
        <div className="relative mt-16 max-w-xl lg:mt-0">
          <p className="reveal text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-accent">Prevention Atlas</p>
          <h1
            className="reveal mt-4 font-display text-4xl font-normal leading-[1.04] tracking-[-0.025em] text-ink-text sm:text-6xl"
            style={{ "--i": 1 } as React.CSSProperties}
          >
            A living view of <em className="italic text-ink-accent">population</em> health.
          </h1>
          <p className="reveal mt-5 max-w-md text-[15px] leading-relaxed text-ink-muted" style={{ "--i": 2 } as React.CSSProperties}>
            Programmes, documented care gaps and the evidence behind them — computed by a deterministic rules engine,
            never guessed.
          </p>
        </div>
        <p className="relative mt-12 text-xs text-ink-faint lg:mt-0">
          Synthetic demonstration data only — no real people. Not clinically validated.
        </p>
      </section>

      <section aria-label="Sign in" className="relative flex items-center justify-center px-6 py-12 sm:px-10">
        <div className="absolute right-4 top-4">
          <ThemeToggle />
        </div>
        <form onSubmit={submit} noValidate className="reveal w-full max-w-sm" style={{ "--i": 2 } as React.CSSProperties}>
          <LogoWordmark className="mb-8 lg:hidden" />
          <h2 className="font-display text-3xl font-medium tracking-[-0.02em] text-foreground">Sign in</h2>
          <p className="mt-2 text-sm text-muted">Staff workspace for population health managers, clinicians and care coordinators.</p>

          {notice && (
            <p role="status" className="mt-5 rounded-xl bg-highlight px-3.5 py-2.5 text-sm text-foreground">
              {notice}
            </p>
          )}

          <div className="mt-7 flex flex-col gap-4">
            <label className="flex flex-col gap-1.5 text-sm font-medium text-foreground">
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
            <label className="flex flex-col gap-1.5 text-sm font-medium text-foreground">
              Password
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={field}
                aria-invalid={error !== null}
              />
            </label>
          </div>

          <div aria-live="assertive" className="min-h-6">
            {error && (
              <p role="alert" className="reveal mt-3 text-sm text-status-error">
                {error}
              </p>
            )}
          </div>

          <button type="submit" disabled={busy} className={buttonClass("primary", "mt-4 w-full")}>
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

          <p className="mt-8 flex gap-2 text-xs leading-relaxed text-faint">
            <Info size={14} aria-hidden="true" className="mt-px shrink-0" />
            <span>
              Accounts are issued by your organization administrator. Patient accounts use the patient portal and cannot
              open this workspace.
            </span>
          </p>
        </form>
      </section>
    </div>
  );
}
