/**
 * Arabic catalog (Modern Standard Arabic), merged from the domain modules. Every English key is
 * required by the type. Terminology: `docs/localization-glossary.md`. Clinical wording must be
 * reviewed by an Arabic clinical language specialist before any real-world deployment.
 */
import type { MessageKey } from "./en";
import { commonAr } from "./common";
import { populationAr } from "./population";
import { programmesAr } from "./programmes";
import { peopleAr } from "./people";
import { coordinationAr } from "./coordination";
import { homeAr } from "./home";
import { adminAr } from "./admin";
import { portalAr } from "./portal";
import { copilotAr } from "./copilot";

export const ar: Record<MessageKey, string> = {
  ...commonAr,
  ...populationAr,
  ...programmesAr,
  ...peopleAr,
  ...coordinationAr,
  ...homeAr,
  ...adminAr,
  ...portalAr,
  ...copilotAr,
};
