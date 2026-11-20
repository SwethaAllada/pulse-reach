import {
  Activity,
  Building,
  CalendarClock,
  ClipboardList,
  KeyRound,
  Layers,
  LayoutDashboard,
  Link2,
  Radar,
  Route,
  ScrollText,
  ShieldCheck,
  Stethoscope,
  UserCog,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { MessageKey, Translate } from "@/lib/i18n/translate";

export type Role = "SYSTEM_ADMIN" | "POPULATION_HEALTH_MANAGER" | "CARE_COORDINATOR" | "CLINICIAN";

export interface NavItem {
  /** A message key, or one per role when the same view means something different to each role. */
  label: MessageKey | Partial<Record<Role, MessageKey>>;
  href: string;
  icon: LucideIcon;
  group: NavGroupId;
  /**
   * Permissions (any of) the view depends on. Only hides navigation the signed-in
   * role cannot use; the backend still authorizes every request.
   */
  requires: string[];
  /** Roles whose navigation lists the item (omitted = every role holding `requires`). */
  roles?: Role[];
}

export type NavGroupId = "home" | "care" | "insight" | "admin" | "reference";

const STAFF_CARE: Role[] = ["POPULATION_HEALTH_MANAGER", "CARE_COORDINATOR", "CLINICIAN"];

export const NAV_ITEMS: NavItem[] = [
  /* Each role's home at "/" — see components/home/role-home.tsx. */
  { label: "nav.population_overview", href: "/", icon: Radar, group: "home", requires: ["insights.read"], roles: ["POPULATION_HEALTH_MANAGER"] },
  { label: "nav.my_worklist", href: "/", icon: ClipboardList, group: "home", requires: ["followups.read"], roles: ["CARE_COORDINATOR"] },
  { label: "nav.my_patients", href: "/", icon: Stethoscope, group: "home", requires: ["patients.read_assigned", "patients.read"], roles: ["CLINICIAN"] },
  { label: "nav.administration", href: "/", icon: LayoutDashboard, group: "home", requires: ["users.read"], roles: ["SYSTEM_ADMIN"] },

  { label: "nav.follow_up", href: "/follow-up", icon: Route, group: "care", requires: ["followups.read"], roles: STAFF_CARE },
  {
    label: "nav.appointments_referrals",
    href: "/appointments",
    icon: CalendarClock,
    group: "care",
    requires: ["appointments.read", "referrals.read"],
    roles: STAFF_CARE,
  },

  {
    label: { POPULATION_HEALTH_MANAGER: "nav.people", CARE_COORDINATOR: "nav.assigned_patients", CLINICIAN: "nav.patient_list" },
    href: "/people",
    icon: Users,
    group: "insight",
    requires: ["patients.read", "patients.read_assigned"],
    roles: STAFF_CARE,
  },
  { label: "nav.programmes", href: "/programmes", icon: Layers, group: "insight", requires: ["rules.read"], roles: STAFF_CARE },
  { label: "nav.panel_insights", href: "/population", icon: Activity, group: "insight", requires: ["insights.read"], roles: ["CARE_COORDINATOR", "CLINICIAN"] },

  { label: "nav.users_roles", href: "/admin/users", icon: UserCog, group: "admin", requires: ["users.read"] },
  { label: "nav.care_team_assignments", href: "/admin/assignments", icon: Link2, group: "admin", requires: ["assignments.manage"] },
  { label: "nav.patient_portal_links", href: "/admin/patient-links", icon: KeyRound, group: "admin", requires: ["patient_links.manage"] },
  { label: "nav.audit_log", href: "/admin/audit", icon: ScrollText, group: "admin", requires: ["audit_logs.read"] },
  { label: "nav.population_aggregation", href: "/admin/population", icon: ShieldCheck, group: "admin", requires: ["population.configure", "population.refresh"] },

  { label: "nav.programme_rules", href: "/programmes", icon: Layers, group: "reference", requires: ["rules.read"], roles: ["SYSTEM_ADMIN"] },
  { label: "nav.facilities", href: "/facilities", icon: Building, group: "reference", requires: ["facilities.read"] },
];

export const NAV_GROUPS: { id: NavGroupId; label: MessageKey }[] = [
  { id: "home", label: "nav.group.home" },
  { id: "care", label: "nav.group.care" },
  { id: "insight", label: "nav.group.insight" },
  { id: "admin", label: "nav.group.admin" },
  { id: "reference", label: "nav.group.reference" },
];

/**
 * Items for the signed-in role. `role === null` (legacy backend, tests without a session) lists
 * every item the permissions allow, with the population overview as home.
 */
export function navItemsFor(role: string | null, can: (...perms: string[]) => boolean): NavItem[] {
  const seen = new Set<string>();
  return NAV_ITEMS.filter((item) => {
    if (!can(...item.requires)) return false;
    if (role === null) {
      if (item.href === "/" && !item.roles?.includes("POPULATION_HEALTH_MANAGER")) return false;
      if (item.href === "/population" || item.label === "nav.programme_rules") return false;
    } else if (item.roles && !item.roles.includes(role as Role)) return false;
    const key = `${item.group}|${item.href}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function navLabel(item: NavItem, role: string | null, t: Translate): string {
  if (typeof item.label === "string") return t(item.label);
  return t(item.label[role as Role] ?? Object.values(item.label)[0]!);
}

export function isNavItemActive(item: NavItem, pathname: string): boolean {
  if (item.href === "/") return pathname === "/";
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

const HOME_LABEL: Record<Role, MessageKey> = {
  POPULATION_HEALTH_MANAGER: "nav.crumb_population",
  CARE_COORDINATOR: "nav.my_worklist",
  CLINICIAN: "nav.my_patients",
  SYSTEM_ADMIN: "nav.administration",
};

/** First breadcrumb: the role's own home. The population home keeps its filter-carrying link. */
export function homeCrumb(role: string | null, t: Translate, populationLink = "/"): { label: string; href: string } {
  const key = HOME_LABEL[role as Role];
  return !key || role === "POPULATION_HEALTH_MANAGER"
    ? { label: t("nav.crumb_population"), href: populationLink }
    : { label: t(key), href: "/" };
}
