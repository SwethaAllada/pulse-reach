import type { Metadata } from "next";
import { Suspense } from "react";
import { ReceivedFilters } from "@/components/population/received-filters";
import { Users } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { NotImplementedState } from "@/components/ui/not-implemented-state";

export const metadata: Metadata = { title: "People" };

export default function PeoplePage() {
  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow="Find"
        title="People"
        subtitle="Discovery workspace for the synthetic cohort — filter, queue and open the people who need attention."
        breadcrumbs={[{ label: "People" }]}
        className="mb-8"
      />
      <Suspense fallback={null}>
        <ReceivedFilters />
      </Suspense>
      <NotImplementedState
        icon={Users}
        title="People discovery arrives in Phase 3"
        description="This workspace will list every synthetic person with programme, region, evidence state and open gaps — fed by the patients and care-gaps APIs."
        roadmap="Filter sentence, ranked list, persistent preview pane, and deep links into each person's case brief."
      />
    </div>
  );
}
