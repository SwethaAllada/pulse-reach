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
