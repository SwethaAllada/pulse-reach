import type { Metadata } from "next";
import { Suspense } from "react";
import { PersonProfile } from "@/components/people/profile/person-profile";
import { LoadingState } from "@/components/ui/loading-state";

export const metadata: Metadata = { title: "Person profile" };

export default function PersonProfilePage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-6 lg:px-8">
          <LoadingState rows={6} />
        </div>
      }
    >
      <PersonProfile />
    </Suspense>
  );
}
