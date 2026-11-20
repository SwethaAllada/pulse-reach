"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, ApiError, holdRequests, releaseRequests } from "@/lib/api/client";
import { clearApiCache } from "@/lib/api/cache";
import type { MeOut } from "@/lib/api/types";
import { clearSession, getSession, setSession, subscribeSession } from "./session";

/**
 * Identity state of the browser session.
 *
 * - `signed_in`: `AUTH_MODE=users`, bearer token valid; permissions come from `GET /me`.
 * - `legacy`:    the backend has no identity layer (`/me` → 404, `AUTH_MODE=legacy`);
 *                reads are public and the backend decides everything.
 * - `signed_out` / `unreachable` / `checking`: self-explanatory.
 *
 * The frontend never authorizes on its own: permissions only shape navigation and
 * explain empty states. Every request is still checked by the backend.
 */
export type AuthState =
  | { status: "checking" }
  | { status: "signed_out"; reason: "none" | "expired" | "signed_out" }
  | { status: "legacy" }
  | { status: "signed_in"; me: MeOut }
  | { status: "unreachable"; message: string };

export type PatientScope = "organization" | "assigned" | "self" | null;

export interface AuthContextValue {
  state: AuthState;
  /** True when any of `perms` is granted (always true in legacy mode — the backend decides). */
  can: (...perms: string[]) => boolean;
  /** Staff-facing workspaces apply; patients and accounts without staff permissions are excluded. */
  isStaff: boolean;
  scope: PatientScope;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  retry: () => void;
}

const STAFF_PERMISSIONS = ["insights.read", "patients.read", "patients.read_assigned", "rules.read", "care_gaps.read"];

function scopeOf(me: MeOut): PatientScope {
  if (me.permissions.includes("patients.read_self")) return "self";
  if (me.permissions.includes("patients.read")) return "organization";
  if (me.permissions.includes("patients.read_assigned")) return "assigned";
  return null;
}

export function buildAuthValue(state: AuthState, actions: Pick<AuthContextValue, "signIn" | "signOut" | "retry">): AuthContextValue {
  const me = state.status === "signed_in" ? state.me : null;
  const can = (...perms: string[]) =>
    state.status === "legacy" || (me !== null && perms.some((p) => me.permissions.includes(p)));
  return {
    state,
    can,
    isStaff: state.status === "legacy" || (me !== null && STAFF_PERMISSIONS.some((p) => me.permissions.includes(p))),
    scope: me ? scopeOf(me) : null,
    ...actions,
  };
}

/** Without a provider (unit tests, legacy embedding) the app behaves as in legacy mode. */
const noop = async () => {};
const AuthContext = createContext<AuthContextValue>(
  buildAuthValue({ status: "legacy" }, { signIn: noop, signOut: noop, retry: () => {} })
);

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>(() => {
    // Hold data requests before any child effect can fire them without a session.
    if (typeof window !== "undefined") holdRequests();
    return { status: "checking" };
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .me(ctrl.signal)
      .then((me) => setState({ status: "signed_in", me }))
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) return setState({ status: "legacy" });
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          return setState({ status: "signed_out", reason: "none" });
        }
        setState({
          status: "unreachable",
          message: err instanceof ApiError ? err.message : "Unexpected error while checking your session.",
        });
      });
    return () => ctrl.abort();
  }, [attempt]);

  // A failed refresh clears the session: return to sign-in instead of showing broken workspaces.
  useEffect(
    () =>
      subscribeSession(() => {
        if (getSession()) return;
        holdRequests();
        clearApiCache();
        setState((prev) => (prev.status === "signed_in" ? { status: "signed_out", reason: "expired" } : prev));
      }),
    []
  );

  const signIn = useCallback(async (email: string, password: string) => {
    clearSession();
    const tokens = await api.login(email, password);
    setSession(tokens);
    clearApiCache();
    const me = await api.me();
    setState({ status: "signed_in", me });
  }, []);

  const signOut = useCallback(async () => {
    try {
      if (getSession()) await api.logout();
    } catch {
      /* The local session is discarded regardless; the server session expires on its own. */
    }
    holdRequests();
    clearApiCache();
    setState({ status: "signed_out", reason: "signed_out" });
    clearSession();
  }, []);

  const retry = useCallback(() => {
    setState({ status: "checking" });
    setAttempt((n) => n + 1);
  }, []);

  const value = useMemo(() => buildAuthValue(state, { signIn, signOut, retry }), [state, signIn, signOut, retry]);

  // Data requests flow only for a resolved staff session (or a legacy backend, which has no sessions).
  useEffect(() => {
    if (value.isStaff && (state.status === "signed_in" || state.status === "legacy")) releaseRequests();
    else holdRequests();
  }, [state, value.isStaff]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function roleLabel(role: string | null | undefined): string {
  switch (role) {
    case "POPULATION_HEALTH_MANAGER":
      return "Population health manager";
    case "CARE_COORDINATOR":
      return "Care coordinator";
    case "CLINICIAN":
      return "Clinician";
    case "SYSTEM_ADMIN":
      return "System administrator";
    case "PATIENT":
      return "Patient";
    default:
      return role ? role.replace(/_/g, " ").toLowerCase() : "No role";
  }
}

export function scopeLabel(scope: PatientScope): string {
  switch (scope) {
    case "organization":
      return "All patients of your organization";
    case "assigned":
      return "Only patients assigned to you";
    case "self":
      return "Your own record only";
    default:
      return "No patient-level access";
  }
}
