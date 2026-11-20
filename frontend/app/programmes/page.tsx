import type { Metadata } from "next";
import { Suspense } from "react";
import { ProgrammesOverview } from "@/components/programmes/programmes-overview";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";
import { LoadingState } from "@/components/ui/loading-state";

export const metadata: Metadata = { title: "Programmes" };

export default function ProgrammesPage() {
  return (
    <PageTransition>
      <Suspense
        fallback={
          <div className="mx-auto w-full max-w-[1280px] px-4 py-8 sm:px-6 lg:px-8">
            <LoadingState rows={6} labelKey="page.loading_programmes" />
          </div>
        }
      >
        <RequirePermission anyOf={["rules.read"]} workspace="nav.programmes">
          <ProgrammesOverview />
        </RequirePermission>
      </Suspense>
    </PageTransition>
  );
}
