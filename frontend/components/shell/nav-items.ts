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
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Population", href: "/", icon: Radar, verb: "Identify" },
  { label: "People", href: "/people", icon: Users, verb: "Find" },
  { label: "Follow-up", href: "/follow-up", icon: Route, verb: "Connect" },
  {
    label: "Appointments & Referrals",
    href: "/appointments",
    icon: CalendarClock,
    verb: "Coordinate",
  },
  { label: "Programmes & Rules", href: "/programmes", icon: Layers, verb: "Explain" },
  { label: "Facilities", href: "/facilities", icon: Building, verb: "Reference" },
];

export function isNavItemActive(item: NavItem, pathname: string): boolean {
  if (item.href === "/") return pathname === "/";
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}
