import type { Metadata } from "next";
import { Building } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { NotImplementedState } from "@/components/ui/not-implemented-state";

export const metadata: Metadata = { title: "Facilities" };

export default function FacilitiesPage() {
  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow="Reference"
        title="Facilities"
        subtitle="Reference register of licensed facilities by region and type — used from care pathways, not as a standalone workspace."
        breadcrumbs={[{ label: "Facilities" }]}
        className="mb-8"
      />
      <NotImplementedState
        icon={Building}
        title="Facility register arrives in a later phase"
        description="A browsable register of facility names, types, regions and licence status."
        roadmap="Client-side filtering by region and type once the facilities API is connected."
      />
    </div>
  );
}
