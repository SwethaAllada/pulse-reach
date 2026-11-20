import { ViewTransition } from "react";

/**
 * Route-level motion. Navigations are React transitions, so this animates when the
 * page enters or leaves: links tagged `nav-forward` (deeper into the atlas journey)
 * slide in from the right, `nav-back` from the left, and untyped navigations rise
 * in place. Reduced-motion users get an instant swap (see globals.css).
 */
export function PageTransition({ children }: { children: React.ReactNode }) {
  return (
    <ViewTransition
      enter={{ "nav-forward": "nav-forward", "nav-back": "nav-back", default: "atlas-enter" }}
      exit={{ "nav-forward": "nav-forward", "nav-back": "nav-back", default: "atlas-exit" }}
      default="none"
    >
      {children}
    </ViewTransition>
  );
}

export const FORWARD = ["nav-forward"];
export const BACK = ["nav-back"];
