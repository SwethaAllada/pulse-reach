/**
 * English catalog — the source of truth for message keys, merged from one module per domain
 * (each module holds the English and Arabic entries side by side). `ar.ts` must define every key
 * (enforced by its type and by `lib/i18n/catalog.test.ts`).
 *
 * Conventions: complete sentences per key, named `{placeholders}` (never concatenate translated
 * fragments), `<base>.one` / `<base>.other` (+ `zero`/`two`/`few`/`many` in Arabic) for plurals.
 * Healthcare terms follow `docs/localization-glossary.md`.
 */
import { commonEn } from "./common";
import { populationEn } from "./population";
import { programmesEn } from "./programmes";
import { peopleEn } from "./people";
import { coordinationEn } from "./coordination";
import { homeEn } from "./home";
import { adminEn } from "./admin";
import { portalEn } from "./portal";
import { copilotEn } from "./copilot";

/** Domain modules, for the duplicate-key check. */
export const EN_MODULES = { commonEn, populationEn, programmesEn, peopleEn, coordinationEn, homeEn, adminEn, portalEn, copilotEn };

export const en = {
  ...commonEn,
  ...populationEn,
  ...programmesEn,
  ...peopleEn,
  ...coordinationEn,
  ...homeEn,
  ...adminEn,
  ...portalEn,
  ...copilotEn,
} as const;

export type MessageKey = keyof typeof en;
