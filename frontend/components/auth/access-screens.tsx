"use client";

import { LogOut, RotateCcw } from "lucide-react";
import { roleLabel, useAuth } from "@/lib/auth/auth-context";
import { API_BASE_URL } from "@/lib/api/client";
import { buttonClass } from "@/components/ui/button-styles";
import { LogoMark } from "@/components/shell/logo";
import { LanguageSwitcher } from "@/components/i18n/language-switcher";
import { useLocale } from "@/lib/i18n/use-locale";

/** First paint while the session is checked against `GET /me`. */
export function CheckingScreen() {
  const { t } = useLocale();
  return (
    <div aria-busy="true" aria-label={t("access.checking")} className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-5">
        <LogoMark className="size-10" />
        <span className="progress-track h-0.5 w-24 rounded-full bg-border text-accent" />
      </div>
    </div>
  );
}

/** Full-page states outside the staff workspace: patient accounts, unreachable or unsupported API. */
export function AccessScreen({ kind, message }: { kind: "not_staff" | "unreachable" | "unsupported"; message?: string }) {
  const { state, signOut, retry } = useAuth();
  const role = state.status === "signed_in" ? state.me.role : null;
  const { t, rich } = useLocale();
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 px-6 text-center">
      <LogoMark className="size-10" />
      <div className="reveal max-w-md">
        {kind === "not_staff" ? (
          <>
            <h1 className="font-display text-3xl font-medium tracking-[-0.02em] text-foreground">
              {t("access.no_workspace_title")}
            </h1>
            <p className="mt-3 text-sm leading-relaxed text-muted">
              {rich("access.no_workspace_body", { role: <span className="text-foreground">{roleLabel(role, t)}</span> })}
            </p>
          </>
        ) : kind === "unsupported" ? (
          <>
            <h1 className="font-display text-3xl font-medium tracking-[-0.02em] text-foreground">
              {t("access.unsupported_title")}
            </h1>
            <p role="alert" className="mt-3 text-sm leading-relaxed text-muted">
              {rich("access.unsupported_body", {
                url: <span className="font-mono text-foreground">{API_BASE_URL}</span>,
                endpoint: <span className="font-mono">{message ?? "/me"}</span>,
                mode: <span className="font-mono">AUTH_MODE=users</span>,
              })}
            </p>
          </>
        ) : (
          <>
            <h1 className="font-display text-3xl font-medium tracking-[-0.02em] text-foreground">{t("access.unavailable_title")}</h1>
            <p role="alert" className="mt-3 text-sm leading-relaxed text-muted">
              {t("access.unavailable_body", { message: message ?? "" })}
            </p>
          </>
        )}
      </div>
      {kind === "not_staff" ? (
        <button type="button" onClick={() => void signOut()} className={buttonClass("secondary")}>
          <LogOut size={15} aria-hidden="true" className="rtl:-scale-x-100" /> {t("user.sign_out")}
        </button>
      ) : (
        <button type="button" onClick={retry} className={buttonClass("primary")}>
          <RotateCcw size={15} aria-hidden="true" /> {t("access.retry")}
        </button>
      )}
      <LanguageSwitcher />
    </div>
  );
}
