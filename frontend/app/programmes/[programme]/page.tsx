import type { Metadata } from "next";
import { Suspense } from "react";
import { ProgrammeDetail } from "@/components/programmes/programme-detail";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";
import { BusyBlock } from "@/components/ui/busy-block";

export const metadata: Metadata = { title: "Programme" };

export default function ProgrammePage() {
  return (
    <PageTransition>
      <Suspense fallback={<BusyBlock labelKey="page.loading_programme" className="skeleton h-[640px] w-full" />}>
        <RequirePermission anyOf={["rules.read"]} workspace="nav.programmes">
          <ProgrammeDetail />
        </RequirePermission>
      </Suspense>
    </PageTransition>
  );
}
