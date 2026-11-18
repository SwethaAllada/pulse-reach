import type { Metadata } from "next";
import { Route } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { NotImplementedState } from "@/components/ui/not-implemented-state";

export const metadata: Metadata = { title: "Follow-up" };

export default function FollowUpPage() {
  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow="Connect"
        title="Follow-up"
        subtitle="Track the care-gap lifecycle from identification through outreach to documented completion."
        breadcrumbs={[{ label: "Follow-up" }]}
        className="mb-8"
      />
      <NotImplementedState
        icon={Route}
        title="Follow-up lanes arrive in a later phase"
        description="Outreach events, appointment records and referral tracking will live here as lanes over the care-gap lifecycle."
        roadmap="Outreach logging, consent gates, dated timelines and documented-completion tracking (backend T-07/T-09/T-10)."
      />
    </div>
  );
}
