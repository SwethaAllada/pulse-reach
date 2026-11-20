"use client";

import { Building2, LogOut, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { roleLabel, scopeLabel, useAuth } from "@/lib/auth/auth-context";
import { cn } from "@/lib/cn";
import { useLocale } from "@/lib/i18n/use-locale";
import { LanguageSwitcher } from "@/components/i18n/language-switcher";

function initials(name: string): string {
  const parts = name.replace(/\(.*?\)/g, "").trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] ?? "?").concat(parts.length > 1 ? parts[parts.length - 1][0] : "").toUpperCase();
}

/** Signed-in identity, role, organization and patient scope — all from `GET /me`. */
export function UserMenu() {
  const { state, scope, signOut } = useAuth();
  const { t, rich } = useLocale();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const me = state.status === "signed_in" ? state.me : null;
  const org = me?.memberships.find((m) => m.organization_id === me.organization_id);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={t("user.menu")}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex h-9 items-center gap-2 rounded-full ps-1 pe-1 text-muted transition-colors hover:bg-surface-sunken hover:text-foreground sm:pe-3"
      >
        <span
          aria-hidden="true"
          className="flex size-7 items-center justify-center rounded-full bg-surface-brand text-[11px] font-semibold text-[var(--on-brand)]"
        >
          {me ? initials(me.user.full_name) : "–"}
        </span>
        <span className="hidden max-w-36 truncate text-xs font-medium text-foreground sm:block">
          {me ? roleLabel(me.role, t) : t("user.legacy_access")}
        </span>
      </button>
      <div
        role="menu"
        aria-hidden={!open}
        className={cn(
          "absolute end-0 top-full z-50 mt-2 w-72 origin-top-right rounded-xl rtl:origin-top-left border border-border bg-surface-raised py-1.5 shadow-[var(--shadow-popover)] transition-[opacity,transform] duration-200 ease-[var(--ease-out)]",
          open ? "scale-100 opacity-100" : "pointer-events-none scale-95 opacity-0"
        )}
      >
        {me ? (
          <>
            <div className="border-b border-border px-4 py-3">
              <p className="font-display text-base font-medium text-foreground">{me.user.full_name}</p>
              <p className="truncate text-xs text-faint">
                <span className="ltr-value">{me.user.email}</span>
              </p>
              <dl className="mt-3 flex flex-col gap-1.5 text-xs">
                <div className="flex items-start gap-2">
                  <ShieldCheck size={13} aria-hidden="true" className="mt-px shrink-0 text-faint" />
                  <dt className="sr-only">{t("user.role")}</dt>
                  <dd className="text-foreground">{roleLabel(me.role, t)}</dd>
                </div>
                {org && (
                  <div className="flex items-start gap-2">
                    <Building2 size={13} aria-hidden="true" className="mt-px shrink-0 text-faint" />
                    <dt className="sr-only">{t("user.organization")}</dt>
                    <dd className="text-muted">{org.organization_name}</dd>
                  </div>
                )}
                <div className="mt-1 rounded-md bg-surface-sunken px-2 py-1.5 text-muted">
                  <dt className="inline text-faint">{t("user.patient_scope")} </dt>
                  <dd className="inline">{scopeLabel(scope, t)}</dd>
                </div>
              </dl>
            </div>
            <div className="border-b border-border px-4 py-2.5">
              <LanguageSwitcher />
            </div>
            <button
              type="button"
              role="menuitem"
              tabIndex={open ? 0 : -1}
              onClick={() => {
                setOpen(false);
                void signOut();
              }}
              className="flex w-full items-center gap-2.5 px-4 py-2 text-start text-sm text-muted hover:bg-surface-sunken hover:text-foreground"
            >
              <LogOut size={15} aria-hidden="true" className="rtl:-scale-x-100" /> {t("user.sign_out")}
            </button>
          </>
        ) : (
          <div className="px-4 py-3">
            <p className="text-sm font-semibold text-foreground">{t("user.legacy_title")}</p>
            <p className="mt-1 text-xs leading-relaxed text-faint">
              {rich("user.legacy_body", {
                flag: <code className="font-mono">NEXT_PUBLIC_ALLOW_LEGACY_BACKEND=true</code>,
                mode: <code className="font-mono">AUTH_MODE=users</code>,
              })}
            </p>
            <LanguageSwitcher className="mt-3" />
          </div>
        )}
      </div>
    </div>
  );
}
