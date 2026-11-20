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

export type Role = "SYSTEM_ADMIN" | "POPULATION_HEALTH_MANAGER" | "CARE_COORDINATOR" | "CLINICIAN";

export interface NavItem {
  /** A label, or one per role when the same view means something different to each role. */
  label: string | Partial<Record<Role, string>>;
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
  { label: "Population overview", href: "/", icon: Radar, group: "home", requires: ["insights.read"], roles: ["POPULATION_HEALTH_MANAGER"] },
  { label: "My worklist", href: "/", icon: ClipboardList, group: "home", requires: ["followups.read"], roles: ["CARE_COORDINATOR"] },
  { label: "My patients", href: "/", icon: Stethoscope, group: "home", requires: ["patients.read_assigned", "patients.read"], roles: ["CLINICIAN"] },
  { label: "Administration", href: "/", icon: LayoutDashboard, group: "home", requires: ["users.read"], roles: ["SYSTEM_ADMIN"] },

  { label: "Follow-up", href: "/follow-up", icon: Route, group: "care", requires: ["followups.read"], roles: STAFF_CARE },
  {
    label: "Appointments & referrals",
    href: "/appointments",
    icon: CalendarClock,
    group: "care",
    requires: ["appointments.read", "referrals.read"],
    roles: STAFF_CARE,
  },

  {
    label: { POPULATION_HEALTH_MANAGER: "People", CARE_COORDINATOR: "Assigned patients", CLINICIAN: "Patient list" },
    href: "/people",
    icon: Users,
    group: "insight",
    requires: ["patients.read", "patients.read_assigned"],
    roles: STAFF_CARE,
  },
  { label: "Programmes", href: "/programmes", icon: Layers, group: "insight", requires: ["rules.read"], roles: STAFF_CARE },
  { label: "Panel insights", href: "/population", icon: Activity, group: "insight", requires: ["insights.read"], roles: ["CARE_COORDINATOR", "CLINICIAN"] },

  { label: "Users & roles", href: "/admin/users", icon: UserCog, group: "admin", requires: ["users.read"] },
  { label: "Care-team assignments", href: "/admin/assignments", icon: Link2, group: "admin", requires: ["assignments.manage"] },
  { label: "Patient portal links", href: "/admin/patient-links", icon: KeyRound, group: "admin", requires: ["patient_links.manage"] },
  { label: "Audit log", href: "/admin/audit", icon: ScrollText, group: "admin", requires: ["audit_logs.read"] },
  { label: "Population aggregation", href: "/admin/population", icon: ShieldCheck, group: "admin", requires: ["population.configure", "population.refresh"] },

  { label: "Programme rules", href: "/programmes", icon: Layers, group: "reference", requires: ["rules.read"], roles: ["SYSTEM_ADMIN"] },
  { label: "Facilities", href: "/facilities", icon: Building, group: "reference", requires: ["facilities.read"] },
];

export const NAV_GROUPS: { id: NavGroupId; label: string }[] = [
  { id: "home", label: "Workspace" },
  { id: "care", label: "Care coordination" },
  { id: "insight", label: "Patients & programmes" },
  { id: "admin", label: "Administration" },
  { id: "reference", label: "Reference" },
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
      if (item.href === "/population" || item.label === "Programme rules") return false;
    } else if (item.roles && !item.roles.includes(role as Role)) return false;
    const key = `${item.group}|${item.href}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function navLabel(item: NavItem, role: string | null): string {
  if (typeof item.label === "string") return item.label;
  return item.label[role as Role] ?? Object.values(item.label)[0]!;
}

export function isNavItemActive(item: NavItem, pathname: string): boolean {
  if (item.href === "/") return pathname === "/";
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

const HOME_LABEL: Record<Role, string> = {
  POPULATION_HEALTH_MANAGER: "Population",
  CARE_COORDINATOR: "My worklist",
  CLINICIAN: "My patients",
  SYSTEM_ADMIN: "Administration",
};

/** First breadcrumb: the role's own home. The population home keeps its filter-carrying link. */
export function homeCrumb(role: string | null, populationLink = "/"): { label: string; href: string } {
  const label = HOME_LABEL[role as Role];
  return !label || role === "POPULATION_HEALTH_MANAGER" ? { label: "Population", href: populationLink } : { label, href: "/" };
}
