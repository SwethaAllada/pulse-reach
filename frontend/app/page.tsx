import { Suspense } from "react";
import { PopulationWorkspace } from "@/components/population/population-workspace";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";

export default function PopulationPage() {
  return (
    <PageTransition>
      <Suspense
        fallback={<div aria-busy="true" aria-label="Loading population workspace" className="skeleton-ink h-[640px] w-full" />}
      >
        <RequirePermission anyOf={["insights.read"]} workspace="The Population workspace">
          <PopulationWorkspace />
        </RequirePermission>
      </Suspense>
    </PageTransition>
  );
}
