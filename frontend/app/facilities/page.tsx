import { Suspense } from "react";
import type { Metadata } from "next";
import { FacilityRegister } from "@/components/facilities/facility-register";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";
import { LoadingState } from "@/components/ui/loading-state";

export const metadata: Metadata = { title: "Facilities" };

export default function FacilitiesPage() {
  return (
    <PageTransition>
      <RequirePermission anyOf={["facilities.read"]} workspace="nav.facilities">
        {/* The register keeps its filters and selection in the URL (`useSearchParams`). */}
        <Suspense fallback={<LoadingState rows={6} label="Loading facilities" className="mx-auto w-full max-w-[1280px] px-4 pt-6 sm:px-6 lg:px-8" />}>
          <FacilityRegister />
        </Suspense>
      </RequirePermission>
    </PageTransition>
  );
}
