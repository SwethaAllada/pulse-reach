import type { Metadata } from "next";
import { Suspense } from "react";
import { PeopleWorkspace } from "@/components/people/people-workspace";
import { LoadingState } from "@/components/ui/loading-state";

export const metadata: Metadata = { title: "People" };

export default function PeoplePage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-6 lg:px-8">
          <LoadingState rows={8} />
        </div>
      }
    >
      <PeopleWorkspace />
    </Suspense>
  );
}
