/**
 * Bearer-token session for `AUTH_MODE=users` (`docs/authentication-and-rbac.md`).
 *
 * Tokens are opaque (`pra_…` / `prr_…`) and only ever come from `POST /auth/login`
 * or `/auth/refresh`; nothing is configured through environment variables. They are
 * kept in `sessionStorage` (per tab, cleared when the tab closes) so a reload does not
 * sign the user out. The access token lives 15 minutes; the refresh token is rotated
 * on every refresh and reuse revokes the session server-side.
 */

export interface TokenPair {
  accessToken: string;
  refreshToken: string;
  /** Epoch ms after which the access token should be refreshed before use. */
  accessExpiresAt: number;
}

const STORAGE_KEY = "pulsereach-session";
const CHANGE_EVENT = "pulsereach-session-change";
/** Refresh slightly before the server-side expiry to avoid racing it. */
const EXPIRY_MARGIN_MS = 30_000;

let memory: TokenPair | null | undefined;

function read(): TokenPair | null {
  if (memory !== undefined) return memory;
  try {
    const raw = typeof window === "undefined" ? null : window.sessionStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as TokenPair) : null;
    memory = parsed && typeof parsed.accessToken === "string" && typeof parsed.refreshToken === "string" ? parsed : null;
  } catch {
    memory = null;
  }
  return memory;
}

export function getSession(): TokenPair | null {
  return read();
}

export function setSession(tokens: { access_token: string; refresh_token: string; expires_in: number }): void {
  memory = {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    accessExpiresAt: Date.now() + tokens.expires_in * 1000 - EXPIRY_MARGIN_MS,
  };
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(memory));
  } catch {
    /* Storage unavailable: the session still works for this page load. */
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function clearSession(): void {
  const had = read() !== null;
  memory = null;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  if (had) window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function isAccessExpired(session: TokenPair): boolean {
  return Date.now() >= session.accessExpiresAt;
}

export function subscribeSession(callback: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, callback);
  return () => window.removeEventListener(CHANGE_EVENT, callback);
}

/** Test hook: forget the cached session so the next read goes to storage. */
export function resetSessionCache(): void {
  memory = undefined;
}
