import type { Metadata } from "next";
import { Suspense } from "react";
import { PopulationWorkspace } from "@/components/population/population-workspace";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";
import { BusyBlock } from "@/components/ui/busy-block";

export const metadata: Metadata = { title: "Panel insights" };

export default function PanelInsightsPage() {
  return (
    <PageTransition>
      <Suspense fallback={<BusyBlock labelKey="page.loading_panel" className="skeleton h-[640px] w-full" />}>
        <RequirePermission anyOf={["insights.read"]} workspace="nav.panel_insights">
          <PopulationWorkspace />
        </RequirePermission>
      </Suspense>
    </PageTransition>
  );
}
