import type { Metadata } from "next";
import { Suspense } from "react";
import { PeopleWorkspace } from "@/components/people/people-workspace";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";
import { LoadingState } from "@/components/ui/loading-state";

export const metadata: Metadata = { title: "People" };

export default function PeoplePage() {
  return (
    <PageTransition>
      <Suspense
        fallback={
          <div className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-6 lg:px-8">
            <LoadingState rows={8} />
          </div>
        }
      >
        <RequirePermission anyOf={["patients.read", "patients.read_assigned"]} workspace="People">
          <PeopleWorkspace />
        </RequirePermission>
      </Suspense>
    </PageTransition>
  );
}
