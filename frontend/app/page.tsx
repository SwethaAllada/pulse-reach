import { Suspense } from "react";
import { PopulationWorkspace } from "@/components/population/population-workspace";

export default function PopulationPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto w-full max-w-[1200px] px-4 sm:px-6 lg:px-8">
          <div aria-busy="true" aria-label="Loading population workspace" className="-mx-4 h-[640px] animate-pulse bg-ink sm:-mx-6 lg:-mx-8" />
        </div>
      }
    >
      <PopulationWorkspace />
    </Suspense>
  );
}
