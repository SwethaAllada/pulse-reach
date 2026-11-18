"use client";

import { useState } from "react";
import { Sidebar } from "./sidebar";
import { TopNavigation } from "./top-navigation";
import { SyntheticBanner } from "./synthetic-banner";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen">
      <Sidebar mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <SyntheticBanner />
        <TopNavigation onMenuClick={() => setMobileOpen(true)} />
        <main id="main-content" className="min-w-0 flex-1">
          {children}
        </main>
      </div>
    </div>
  );
}
