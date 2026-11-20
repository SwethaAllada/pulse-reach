import type { Metadata } from "next";
import { Suspense } from "react";
import { ProgrammeDetail } from "@/components/programmes/programme-detail";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";

export const metadata: Metadata = { title: "Programme" };

export default function ProgrammePage() {
  return (
    <PageTransition>
      <Suspense fallback={<div aria-busy="true" aria-label="Loading programme" className="skeleton h-[640px] w-full" />}>
        <RequirePermission anyOf={["rules.read"]} workspace="Programmes">
          <ProgrammeDetail />
        </RequirePermission>
      </Suspense>
    </PageTransition>
  );
}
