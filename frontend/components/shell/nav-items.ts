import {
  Building,
  CalendarClock,
  Layers,
  Radar,
  Route,
  Users,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Optional verb eyebrow shown under the label in expanded mode. */
  verb?: string;
  /** Journey folio ("01"…) for the atlas journey items. */
  index?: string;
  group: "journey" | "coordinate";
  /**
   * Permissions (any of) the view depends on. Only hides navigation the signed-in
   * role cannot use; the backend still authorizes every request.
   */
  requires: string[];
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Population", href: "/", icon: Radar, verb: "Identify", index: "01", group: "journey", requires: ["insights.read"] },
  { label: "Programmes", href: "/programmes", icon: Layers, verb: "Explain", index: "02", group: "journey", requires: ["rules.read"] },
  {
    label: "People",
    href: "/people",
    icon: Users,
    verb: "Find",
    index: "03",
    group: "journey",
    requires: ["patients.read", "patients.read_assigned"],
  },
  { label: "Follow-up", href: "/follow-up", icon: Route, verb: "Connect", group: "coordinate", requires: ["followups.read"] },
  {
    label: "Appointments & Referrals",
    href: "/appointments",
    icon: CalendarClock,
    verb: "Coordinate",
    group: "coordinate",
    requires: ["appointments.read", "referrals.read"],
  },
  { label: "Facilities", href: "/facilities", icon: Building, verb: "Reference", group: "coordinate", requires: ["facilities.read"] },
];

export const NAV_GROUPS: { id: NavItem["group"]; label: string }[] = [
  { id: "journey", label: "Atlas" },
  { id: "coordinate", label: "Coordinate" },
];

export function isNavItemActive(item: NavItem, pathname: string): boolean {
  if (item.href === "/") return pathname === "/";
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}
