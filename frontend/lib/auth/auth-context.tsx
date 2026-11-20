"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  allowUnauthenticatedRequests,
  api,
  ApiError,
  holdRequests,
  identityEndpointMissing,
  releaseRequests,
  allowPortalRequests,
  resetIdentityProbe,
} from "@/lib/api/client";
import { clearApiCache } from "@/lib/api/cache";
import type { MeOut } from "@/lib/api/types";
import { legacyBackendAllowed } from "./mode";
import { clearSession, getSession, setSession, subscribeSession } from "./session";

/**
 * Identity state of the browser session.
 *
 * - `signed_in`:   `AUTH_MODE=users`, bearer token valid; permissions come from `GET /me`.
 * - `unsupported`: the backend has no identity layer (`/me`, `/auth/login` or `/auth/refresh`
 *                  answered 404 — `AUTH_MODE=legacy` or a pre-authentication API). Nothing is
 *                  loaded: the workspace never falls back to unauthenticated requests.
 * - `legacy`:      the same backend, accepted only because local development explicitly allowed
 *                  it (`legacyBackendAllowed`); reads are public and the backend decides everything.
 * - `signed_out` / `unreachable` / `checking`: self-explanatory.
 *
 * The frontend never authorizes on its own: permissions only shape navigation and
 * explain empty states. Every request is still checked by the backend.
 */
export type AuthState =
  | { status: "checking" }
  | { status: "signed_out"; reason: "none" | "expired" | "signed_out" }
  | { status: "legacy" }
  | { status: "unsupported"; endpoint: string }
  | { status: "signed_in"; me: MeOut }
  | { status: "unreachable"; message: string };

export type PatientScope = "organization" | "assigned" | "self" | null;

export interface AuthContextValue {
  state: AuthState;
  /** True when any of `perms` is granted (always true in legacy mode — the backend decides). */
  can: (...perms: string[]) => boolean;
  /** Staff-facing workspaces apply; patients and accounts without staff permissions are excluded. */
  isStaff: boolean;
  /** A patient account: only the patient portal (`/portal/*`) applies. */
  isPatient: boolean;
  /** The signed-in role (null in legacy mode). */
  role: string | null;
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

/** Patient accounts never open staff workspaces, whatever other permissions they hold. */
function isPatientAccount(me: MeOut): boolean {
  return me.role === "PATIENT" || me.permissions.includes("patients.read_self");
}

export function buildAuthValue(state: AuthState, actions: Pick<AuthContextValue, "signIn" | "signOut" | "retry">): AuthContextValue {
  const me = state.status === "signed_in" ? state.me : null;
  const can = (...perms: string[]) =>
    state.status === "legacy" || (me !== null && perms.some((p) => me.permissions.includes(p)));
  return {
    state,
    can,
    isStaff:
      state.status === "legacy" ||
      (me !== null && !isPatientAccount(me) && STAFF_PERMISSIONS.some((p) => me.permissions.includes(p))),
    isPatient: me !== null && isPatientAccount(me),
    role: me?.role ?? null,
    scope: me ? scopeOf(me) : null,
    ...actions,
  };
}

/** A `GET /me` body that is not a PulseReach identity (e.g. an HTML fallback) is not a session. */
function isMe(value: unknown): value is MeOut {
  const v = value as Partial<MeOut> | null;
  return !!v && typeof v === "object" && Array.isArray(v.permissions) && !!v.user && typeof v.user.user_id === "string";
}

/**
 * Without a provider (unit tests of individual views) permissions are open; the API client
 * still refuses data requests that carry no access token.
 */
const noop = async () => {};
const AuthContext = createContext<AuthContextValue>(
  buildAuthValue({ status: "legacy" }, { signIn: noop, signOut: noop, retry: () => {} })
);

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

function noIdentityLayer(endpoint: string): AuthState {
  return legacyBackendAllowed() ? { status: "legacy" } : { status: "unsupported", endpoint };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>(() => {
    // Hold data requests before any child effect can fire them without a session.
    if (typeof window !== "undefined") {
      holdRequests();
      allowUnauthenticatedRequests(false);
    }
    return { status: "checking" };
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    resetIdentityProbe();
    api
      .me(ctrl.signal)
      .then((me) => {
        if (!isMe(me)) throw new ApiError("The API at this address did not return a PulseReach identity.", null, "/me");
        setState({ status: "signed_in", me });
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) {
          clearSession();
          return setState(noIdentityLayer("/me"));
        }
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

  // A failed refresh clears the session: return to sign-in (or report a backend without
  // `/auth/refresh`) instead of showing broken workspaces.
  useEffect(
    () =>
      subscribeSession(() => {
        if (getSession()) return;
        holdRequests();
        clearApiCache();
        const missing = identityEndpointMissing();
        setState((prev) =>
          prev.status !== "signed_in" ? prev : missing ? noIdentityLayer(missing) : { status: "signed_out", reason: "expired" }
        );
      }),
    []
  );

  const signIn = useCallback(async (email: string, password: string) => {
    clearSession();
    clearApiCache();
    let me: MeOut;
    try {
      setSession(await api.login(email, password));
      me = await api.me();
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        clearSession();
        return setState(noIdentityLayer(identityEndpointMissing() ?? "/auth/login"));
      }
      clearSession();
      throw err;
    }
    if (!isMe(me)) {
      clearSession();
      throw new ApiError("The API at this address did not return a PulseReach identity.", null, "/me");
    }
    clearApiCache();
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

  // Data requests flow only for a resolved staff session, or an explicitly allowed legacy backend.
  useEffect(() => {
    const legacy = state.status === "legacy" && legacyBackendAllowed();
    allowUnauthenticatedRequests(legacy);
    allowPortalRequests(state.status === "signed_in" && value.isPatient);
    if (value.isStaff && (state.status === "signed_in" || legacy)) releaseRequests();
    else holdRequests();
  }, [state, value.isStaff, value.isPatient]);
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
