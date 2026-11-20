<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Verification

- `npx tsc --noEmit` · `npm run lint` · `npm test` (Vitest + Testing Library, jsdom) · `npm run build`
- Default Node here is 22.5.1 (npm 8): keep Vitest 3.x / Vite 6.x — Vitest 5 / Vite 8 need Node ≥ 22.12.
- `cacheComponents` is on: any `usePathname`/`useSearchParams`/`useParams` read must sit inside `<Suspense>` or dynamic routes (e.g. `/people/[personId]`) fail `next build` prerendering.
- The Population workspace reads the live API (`NEXT_PUBLIC_API_URL`, default `http://localhost:8000`); backend CORS allows `http://localhost:3000` by default (`CORS_ORIGINS`).

## Auth (bearer tokens, `lib/auth/`, `lib/api/client.ts`)

- `AuthProvider` resolves the session via `GET /me`: 401 → sign-in screen, else roles/permissions. A 404 from `/me`, `/auth/login`
  or `/auth/refresh` (no identity layer) → `unsupported` screen, nothing loaded; only a dev build with
  `NEXT_PUBLIC_ALLOW_LEGACY_BACKEND=true` accepts it as `legacy` (`lib/auth/mode.ts`; `next.config.ts` refuses the flag in production).
  Tokens live in `sessionStorage` (`lib/auth/session.ts`); the client attaches `Authorization`, rotates once on 401 (single-flight refresh)
  and refuses (never sends) a data request without a token unless `allowUnauthenticatedRequests` was set for an allowed legacy backend.
  Patient accounts (`PATIENT` role or `patients.read_self`) are never staff.
- The API client *holds* data requests (`holdRequests`/`releaseRequests`) until a staff session exists — `AppShell` keeps the
  workspace tree rendered (`inert`) so segments stay prerenderable. Don't gate children with a hidden `<Activity>` (drops the segment
  from instant-navigation validation) or by not rendering them.
- `can(...)` only shapes nav/empty states; 403 → `forbidden` resource state (`lib/programmes/use-programmes-data.ts`), never fake zeros.
- Tests without `AuthProvider` get all permissions in the UI; `test/setup.ts` signs every test in (`pra_test` session) because the
  client refuses tokenless requests. Use `test/fixtures.ts` `me(role, ROLE_PERMISSIONS[role])` for role tests — the matrix in
  `test/role-permissions.json` is checked against the backend by `backend/tests/test_rbac.py`.
- Programme views read `GET /programmes/{pathway}/summary` (server-side counts; `null` = suppressed, never 0). The overview fetches no
  patient/care-gap pages; the detail still loads members for the lattice/member list. Fake backend: `fakeSummaryConfig.minCellSize`.

## Design system ("Prevention Atlas")

- Tokens in `app/globals.css` per `[data-theme]`, including the `--ink-*` plate (teal in light, midnight in dark). Components use
  semantic tokens only (theme tests reject hex/rgba in inline styles). Motion: `.reveal`, `.grow-x/.grow-y`, `.skeleton(-ink)`,
  `<PageTransition>` + `Link transitionTypes={FORWARD|BACK}`; all disabled under `prefers-reduced-motion`.
- Shared primitives: `components/ui/{plate,figure,button-styles,segmented,permission-notice,page-header}`.

## Visual QA

- Disposable backend: from `backend/`, `DATA_SOURCE=memory DEMO_IDENTITY_SEED=true DEMO_IDENTITY_PASSWORD=<passphrase>
  CORS_ORIGINS=http://localhost:3100 .venv/bin/python -m uvicorn app.main:app --port 8001`, then
  `NEXT_PUBLIC_API_URL=http://localhost:8001 npx next dev -p 3100`; demo users `{manager,clinician,coordinator,admin,patient}.a@demo.pulsereach.invalid`.
