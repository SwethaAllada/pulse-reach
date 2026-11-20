"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { roleLabel, useAuth } from "@/lib/auth/auth-context";
import { API_BASE_URL } from "@/lib/api/client";
import { buttonClass } from "@/components/ui/button-styles";
import { LogoMark } from "@/components/shell/logo";
import { AtlasOrnament } from "./atlas-ornament";

/** First paint while the session is checked against `GET /me` — the atlas plate, nothing else. */
export function CheckingScreen() {
  return (
    <div aria-busy="true" aria-label="Checking your session" className="flex min-h-screen items-center justify-center bg-ink">
      <div className="flex flex-col items-center gap-6">
        <AtlasOrnament className="w-48 opacity-80" />
        <span className="progress-track h-0.5 w-24 rounded-full bg-ink-line text-ink-accent" />
      </div>
    </div>
  );
}

/** Full-page states outside the staff workspace: patient accounts, unreachable or unsupported API. */
export function AccessScreen({ kind, message }: { kind: "not_staff" | "unreachable" | "unsupported"; message?: string }) {
  const { state, signOut, retry } = useAuth();
  const role = state.status === "signed_in" ? state.me.role : null;
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 px-6 text-center">
      <LogoMark className="size-10" />
      <div className="reveal max-w-md">
        {kind === "not_staff" ? (
          <>
            <h1 className="font-display text-3xl font-medium tracking-[-0.02em] text-foreground">
              This workspace is for care teams
            </h1>
            <p className="mt-3 text-sm leading-relaxed text-muted">
              You are signed in as <span className="text-foreground">{roleLabel(role)}</span>. Population, programme and
              people views are staff-facing and are not available to this account. Patients use the PulseReach patient
              portal.
            </p>
          </>
        ) : kind === "unsupported" ? (
          <>
            <h1 className="font-display text-3xl font-medium tracking-[-0.02em] text-foreground">
              This API does not support sign-in
            </h1>
            <p role="alert" className="mt-3 text-sm leading-relaxed text-muted">
              The PulseReach API at <span className="font-mono text-foreground">{API_BASE_URL}</span> has no authentication
              endpoint (<span className="font-mono">{message ?? "/me"}</span> is not available). The staff workspace needs
              a backend running <span className="font-mono">AUTH_MODE=users</span>, so nothing is loaded from this one.
            </p>
          </>
        ) : (
          <>
            <h1 className="font-display text-3xl font-medium tracking-[-0.02em] text-foreground">The API is unavailable</h1>
            <p role="alert" className="mt-3 text-sm leading-relaxed text-muted">
              {message} Nothing is shown in place of real data.
            </p>
          </>
        )}
      </div>
      {kind === "not_staff" ? (
        <button type="button" onClick={() => void signOut()} className={buttonClass("secondary")}>
          <LogOut size={15} aria-hidden="true" /> Sign out
        </button>
      ) : (
        <button type="button" onClick={retry} className={buttonClass("primary")}>
          <RotateCcw size={15} aria-hidden="true" /> Retry
        </button>
      )}
    </div>
  );
}
