import type { Metadata } from "next";
import { Layers } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { NotImplementedState } from "@/components/ui/not-implemented-state";

export const metadata: Metadata = { title: "Programmes & Rules" };

export default function ProgrammesPage() {
  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow="Explain"
        title="Programmes &amp; Rules"
        subtitle="The screening packages and well-child visit rules — with provenance, verification state and open questions."
        breadcrumbs={[{ label: "Programmes & Rules" }]}
        className="mb-8"
      />
      <NotImplementedState
        icon={Layers}
        title="Programme explorer arrives in a later phase"
        description="Browse IFHAS packages and Well-Child visits as structured rule sets, each with source citations and verification status."
        roadmap="Programme rings, rule detail pages, open-question register and people-affected deep links."
      />
    </div>
  );
}
