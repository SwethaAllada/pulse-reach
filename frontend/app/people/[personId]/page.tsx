import type { Metadata } from "next";
import { Suspense } from "react";
import { PersonProfile } from "@/components/people/profile/person-profile";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";
import { LoadingState } from "@/components/ui/loading-state";

export const metadata: Metadata = { title: "Person profile" };

export default function PersonProfilePage() {
  return (
    <PageTransition>
      <Suspense
        fallback={
          <div className="mx-auto w-full max-w-[1280px] px-4 py-8 sm:px-6 lg:px-8">
            <LoadingState rows={6} />
          </div>
        }
      >
        <RequirePermission anyOf={["patients.read", "patients.read_assigned"]} workspace="page.person_profiles">
          <PersonProfile />
        </RequirePermission>
      </Suspense>
    </PageTransition>
  );
}
