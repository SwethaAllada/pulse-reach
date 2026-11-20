import type { Metadata } from "next";
import { Suspense } from "react";
import { RuleDetailView } from "@/components/programmes/rule-detail-view";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";
import { LoadingState } from "@/components/ui/loading-state";

export const metadata: Metadata = { title: "Programme rule" };

export default function ProgrammeRulePage() {
  return (
    <PageTransition>
      <Suspense
        fallback={
          <div className="mx-auto w-full max-w-[1280px] px-4 py-8 sm:px-6 lg:px-8">
            <LoadingState rows={6} label="Loading rule" />
          </div>
        }
      >
        <RequirePermission anyOf={["rules.read"]} workspace="Programme rules">
          <RuleDetailView />
        </RequirePermission>
      </Suspense>
    </PageTransition>
  );
}
