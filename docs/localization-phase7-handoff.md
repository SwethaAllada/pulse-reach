# Phase 7 → shared localization layer (handoff)

The map and facility UI (`components/population/geo/*`, `components/facilities/*`, `lib/population/geo.ts`,
`app/facilities`) is owned by Phase 7 and was **not** translated by the localization workstream. Phase 7 adopts the
shared layer itself. Do not add another translation mechanism.

## API (`frontend/lib/i18n/`)

- Components: `const { t, tp, rich, number, date, dateTime, locale, dir } = useLocale()` from `@/lib/i18n/use-locale`.
  - `t(key, params)` → string; `rich(key, { name: <jsx/> })` for sentences containing elements.
  - `tp(base, n)` plurals: define `base.zero|one|two|few|many|other` in both languages.
  - `number(n)` uses Western digits in Arabic.
- Keys: add a module `lib/i18n/messages/geo.ts` exporting `geoEn` (English) and `geoAr: Record<keyof typeof geoEn, string>`.
  Register it in `messages/en.ts` / `messages/ar.ts` (spread + `EN_MODULES`).
  - Prefix: `geo.` for map keys, `facility.` for directory keys.
  - Placeholders must match in both languages. `lib/i18n/catalog.test.ts` enforces parity and no untranslated Arabic.
- Render rule: never call module `t()` from `@/lib/i18n/translate` during render, because streamed boundaries hydrate after the locale switch. Use the hook.
  Pass the hook's `t` to helpers. Module `t` is fine in event handlers and async code.
- Helpers that already take a translator: `regionLabel(id, t)`, `pathwayLabel(p, t, short?)`, `sexLabel`, `filterChips(f, t)`
  (`lib/population/filters`). Region names are the official Arabic names (أبوظبي، العين، الظفرة).
- Data: `cached()` keys and `useResource` are per language. A language switch re-fetches backend-localized responses
  (population alerts' `title`/`explanation`) while keeping the loaded data on screen. Custom loaders should add `locale` to their keys.

## What to localize

Map controls, layer names, legends, tooltips/popovers, side panels, facility detail, the directory table (headers, pager,
filters, "Unknown/Public/Private"), facility types (`FACILITY_LAYER_META`), unmapped-area explanations, fallback and loading states.

## Keep as source data

Facility names, official geographic names published by the register, licence statuses and ids.
Render them unchanged with `dir="auto"` (Latin names inside Arabic UI), and wrap ids/codes in `<span className="ltr-value">`.

## RTL

- Use logical Tailwind classes only (`ms/me/ps/pe/start/end/border-s/border-e/text-start/text-end`).
- Flip only reading-direction icons (`rtl:-scale-x-100`).
- Do **not** mirror the map canvas, coordinates, compass or scale. MapLibre controls can stay in their corner, or move to
  `top-left` under `dir="rtl"`. Leave geographic positioning and interaction logic unchanged.
- Add converted files to `CONVERTED` in `lib/i18n/catalog.test.ts` (no hardcoded English, no physical left/right classes).

## Already touched by the localization branch (merge note)

- `components/facilities/facility-register.tsx`: `regionLabel(f.region_id, t)`, because the helper signature changed.
- `app/facilities/page.tsx`: `workspace="nav.facilities"`, because `RequirePermission` now takes a message key.
