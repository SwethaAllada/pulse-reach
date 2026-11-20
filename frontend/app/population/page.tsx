import type { Metadata } from "next";
import { Suspense } from "react";
import { PopulationWorkspace } from "@/components/population/population-workspace";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";

export const metadata: Metadata = { title: "Panel insights" };

export default function PanelInsightsPage() {
  return (
    <PageTransition>
      <Suspense fallback={<div aria-busy="true" aria-label="Loading panel insights" className="skeleton h-[640px] w-full" />}>
        <RequirePermission anyOf={["insights.read"]} workspace="Panel insights">
          <PopulationWorkspace />
        </RequirePermission>
      </Suspense>
    </PageTransition>
  );
}
