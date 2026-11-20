"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth/auth-context";
import { SignInScreen } from "@/components/auth/sign-in-screen";
import { AccessScreen, CheckingScreen } from "@/components/auth/access-screens";
import { Sidebar } from "./sidebar";
import { TopNavigation } from "./top-navigation";
import { SyntheticBanner } from "./synthetic-banner";

/**
 * The workspace tree is always rendered so route segments stay prerenderable. Until a
 * staff session exists it sits `inert` under the sign-in / access screen, and the API
 * client holds its requests (see `holdRequests`), so nothing is fetched unauthenticated.
 * The tree is keyed by identity: one user's loaded state never surfaces for another.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { state, isStaff } = useAuth();
  const ready = (state.status === "signed_in" || state.status === "legacy") && isStaff;
  const identity =
    state.status === "signed_in" ? `${state.me.user.user_id}|${state.me.organization_id ?? ""}` : state.status;

  const gate =
    state.status === "checking" ? (
      <CheckingScreen />
    ) : state.status === "signed_out" ? (
      <SignInScreen reason={state.reason} />
    ) : state.status === "unreachable" ? (
      <AccessScreen kind="unreachable" message={state.message} />
    ) : !isStaff ? (
      <AccessScreen kind="not_staff" />
    ) : null;

  return (
    <>
      {gate && <div className="fixed inset-0 z-[70] overflow-y-auto bg-background">{gate}</div>}
      <div key={identity} inert={!ready} aria-hidden={!ready || undefined} className="flex min-h-screen">
        <Sidebar mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} />
        <div className="flex min-w-0 flex-1 flex-col">
          <SyntheticBanner />
          <TopNavigation onMenuClick={() => setMobileOpen(true)} />
          <main id="main-content" className="min-w-0 flex-1">
            {children}
          </main>
        </div>
      </div>
    </>
  );
}
