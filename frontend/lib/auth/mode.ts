/**
 * Whether this build may accept a backend without an identity layer (`AUTH_MODE=legacy` or a
 * pre-authentication API, both answering `GET /me` with 404).
 *
 * Off unless explicitly enabled for local development with
 * `NEXT_PUBLIC_ALLOW_LEGACY_BACKEND=true`, and never in a production build: `next.config.ts`
 * refuses to build or start with the flag set, and this check ignores it under
 * `NODE_ENV=production`. Without it such a backend is reported as unsupported and no data
 * request is ever sent without a staff session.
 */
export function legacyBackendAllowed(): boolean {
  return process.env.NODE_ENV !== "production" && process.env.NEXT_PUBLIC_ALLOW_LEGACY_BACKEND === "true";
}
