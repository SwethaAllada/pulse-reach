import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { EN_MODULES, en } from "./messages/en";
import { ar } from "./messages/ar";
import { formatDate, formatNumber } from "./format";
import { translate, translateRich } from "./translate";

const ARABIC = /[\u0600-\u06FF]/;
const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

/**
 * Values that are intentionally identical in both catalogs: language names shown in their own
 * language, and technical examples. Everything else must be translated — an English string in the
 * Arabic catalog would silently show English in the Arabic interface.
 */
const SAME_IN_BOTH = new Set(["language.en", "language.ar", "auth.email_placeholder", "pop.pathway.ifhas_short", "pop.cohort.aria",
  "people.age.18_39", "people.age.40_59", "prog.plate.standing_count", "person.trace.gap_reason", "list.sep", "list.sep_strong",
]);

describe("English / Arabic catalogs", () => {
  it("define exactly the same keys", () => {
    expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());
  });

  it("use the same placeholders per key", () => {
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      // Arabic singular/dual forms state the number in words ("شخص واحد", "شخصان").
      if (/[._](one|two)$/.test(key)) expect(placeholders(en[key]), key).toEqual(expect.arrayContaining(placeholders(ar[key])));
      else expect(placeholders(ar[key]), key).toEqual(placeholders(en[key]));
    }
  });

  it("have no key defined in two domain modules", () => {
    const total = Object.values(EN_MODULES).reduce((n: number, m: object) => n + Object.keys(m).length, 0);
    expect(Object.keys(en)).toHaveLength(total);
  });

  it("have no untranslated Arabic entries", () => {
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      if (SAME_IN_BOTH.has(key)) continue;
      expect(ar[key], key).not.toBe(en[key]);
      expect(ARABIC.test(ar[key]), `${key} has no Arabic text`).toBe(true);
    }
  });

  it("keep Arabic out of the English catalog", () => {
    for (const [key, value] of Object.entries(en)) if (key !== "language.ar") expect(ARABIC.test(value), key).toBe(false);
  });

  it("has plural forms for every plural key in both locales", () => {
    // A plural base defines `.one` as well; a plain `.other` key (e.g. an enum value) is not a plural.
    const bases = Object.keys(en)
      .filter((k) => k.endsWith(".other"))
      .map((k) => k.slice(0, -".other".length))
      .filter((b) => `${b}.one` in en);
    for (const base of bases) {
      for (const form of ["zero", "one", "two", "few", "many", "other"]) expect(Object.keys(en), base).toContain(`${base}.${form}`);
    }
  });
});

describe("translate", () => {
  it("interpolates and isolates values inside Arabic sentences", () => {
    expect(translate("en", "api.forbidden", { path: "/patients" })).toBe("Your role does not have access to /patients (403).");
    expect(translate("ar", "api.forbidden", { path: "/patients" })).toBe("لا يملك دورك صلاحية الوصول إلى \u2068/patients\u2069 (403).");
  });

  it("keeps rich sentences whole and isolates nodes with <bdi> in Arabic", () => {
    const parts = translateRich("ar", "access.requires_permission", { permission: "rules.read" });
    expect(parts).toHaveLength(3);
    expect((parts[1] as { type: string }).type).toBe("bdi");
  });
});

describe("locale formatting", () => {
  it("formats dates with Gregorian month names and Western digits, as the backend does", () => {
    expect(formatDate("2026-11-16", undefined, "en")).toBe("16 Nov 2026");
    expect(formatDate("2026-11-16", undefined, "ar")).toBe("16 نوفمبر 2026");
  });

  it("keeps Western digits in Arabic numbers", () => {
    expect(formatNumber(12345, undefined, "ar")).toMatch(/^12[,٬]345$/);
    expect(formatNumber(12345, undefined, "en")).toBe("12,345");
  });
});

/*
 * Files converted to the shared localization layer and logical (direction-aware) CSS. The list
 * grows with each converted workspace; a regression here means hardcoded English or a physical
 * left/right class crept back in.
 */
const CONVERTED = [
  "components/shell/sidebar.tsx",
  "components/shell/top-navigation.tsx",
  "components/shell/search-input.tsx",
  "components/shell/notification-menu.tsx",
  "components/shell/synthetic-banner.tsx",
  "components/shell/user-menu.tsx",
  "components/shell/skip-link.tsx",
  "components/auth/sign-in-screen.tsx",
  "components/auth/access-screens.tsx",
  "components/auth/require-permission.tsx",
  "components/theme/theme-toggle.tsx",
  "components/i18n/language-switcher.tsx",
  "components/ui/page-header.tsx",
  "components/ui/permission-notice.tsx",
  "components/ui/loading-state.tsx",
  "components/ui/not-implemented-state.tsx",
  "components/ui/plate.tsx",
  "components/ui/segmented.tsx",
  "components/ui/empty-state.tsx",
  "components/ui/figure.tsx",
  "components/ui/section-header.tsx",
  "components/ui/busy-block.tsx",
  "components/shell/document-title.tsx",
  "components/population/population-workspace.tsx",
  "components/population/population-overview.tsx",
  "components/population/population-filters.tsx",
  "components/population/population-insights.tsx",
  "components/population/cohort-panel.tsx",
  "components/population/cohort-comparison.tsx",
  "components/population/received-filters.tsx",
  "components/population/unavailable-capabilities.tsx",
  "components/constellation/cohort-legend.tsx",
  "components/programmes/programmes-overview.tsx",
  "components/programmes/programme-detail.tsx",
  "components/programmes/programme-sections.tsx",
  "components/programmes/composition.tsx",
  "components/programmes/organization-trend.tsx",
  "components/programmes/resource-state.tsx",
  "components/programmes/rule-detail-view.tsx",
  "components/people/people-workspace.tsx",
  "components/people/people-results.tsx",
  "components/people/people-care-filters.tsx",
  "components/people/people-id-search.tsx",
  "components/people/programme-history.tsx",
  "components/people/profile/person-profile.tsx",
  "components/people/profile/assessment-section.tsx",
  "components/people/profile/care-gaps.tsx",
  "components/people/profile/evidence-trace.tsx",
  "components/home/role-home.tsx",
  "components/admin/admin-overview.tsx",
  "components/admin/admin-pages.tsx",
  "components/coordination/primitives.tsx",
  "components/coordination/follow-up-workspace.tsx",
  "components/coordination/create-task-form.tsx",
  "components/coordination/outreach-panel.tsx",
  "components/coordination/schedule-form.tsx",
  "components/coordination/task-detail.tsx",
  "components/coordination/appointments-workspace.tsx",
  "components/people/profile/coordination-section.tsx",
  "components/portal/patient-portal.tsx",
  "components/copilot/copilot-panel.tsx",
];
const ROOT = join(__dirname, "..", "..");
const PHYSICAL = /(?<![\w-])-?(?:[a-z]+:)*(?:ml|mr|pl|pr|left|right|border-l|border-r|rounded-l|rounded-r|rounded-tl|rounded-tr|rounded-bl|rounded-br|space-x|text-left|text-right|float-left|float-right)(?:-[\w.[\]/%-]+)?(?![\w-])/;
/** Technical literals that stay as written (env flags, shortcuts). */
const TECHNICAL = /^`?(?:[A-Z0-9_=./:⌘-]+|[a-z0-9]+(?:_[a-z0-9]+)+|(?:SYNTH-[A-Z]+-[\d…]+(?:\s*\/\s*)?)+|(?:GET|POST|PATCH) \/[\w/{}?=.-]*)`?$/;

describe("converted components", () => {
  it("recognises physical direction classes", () => {
    for (const c of ["ml-2", "lg:pr-3", "text-left", "-left-1", "border-r", "right-0"]) expect(PHYSICAL.test(c), c).toBe(true);
    for (const c of ["ms-2", "pe-3", "text-start", "start-0", "border-e", "end-0", "rounded-full"]) expect(PHYSICAL.test(c), c).toBe(false);
  });

  it.each(CONVERTED)("%s uses logical CSS only", (file) => {
    const src = readFileSync(join(ROOT, file), "utf8");
    const classes = [...src.matchAll(/className=(?:"([^"]*)"|\{[^}]*?"([^"]*)")/g), ...src.matchAll(/"([^"]*\b(?:ml|mr|pl|pr|left|right)-[^"]*)"/g)]
      .flatMap((m) => (m[1] ?? m[2] ?? "").split(/\s+/))
      .filter((c) => c && !c.startsWith("rtl:") && !c.includes("translate"));
    expect(classes.filter((c) => PHYSICAL.test(c)), file).toEqual([]);
  });

  it.each(CONVERTED)("%s has no hardcoded user-facing English", (file) => {
    const src = readFileSync(join(ROOT, file), "utf8").replace(/\/\*[\s\S]*?\*\/|\{\/\*[\s\S]*?\*\/\}|^\s*\/\/.*$/gm, "");
    const text = [...src.matchAll(/>([^<>{}]*[A-Za-z]{2,}[^<>{}]*)</g)]
      .map((m) => m[1].trim())
      // Drop code between JSX nodes (object keys in `rich(...)` maps, expressions).
      .filter((s) => s && !TECHNICAL.test(s) && !/^[,\s]*\w+:$/.test(s) && !/[=();]|=>|\bconst\b|\breturn\b|\bPromise\b/.test(s));
    const attrs = [...src.matchAll(/\b(?:aria-label|placeholder|title|label)="([^"]*[A-Za-z][^"]*)"/g)].map((m) => m[1]).filter((s) => !TECHNICAL.test(s));
    expect([...text, ...attrs], file).toEqual([]);
  });
});
