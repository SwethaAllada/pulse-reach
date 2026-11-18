import type { Metadata } from "next";
import { CalendarClock } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { NotImplementedState } from "@/components/ui/not-implemented-state";

export const metadata: Metadata = { title: "Appointments & Referrals" };

export default function AppointmentsPage() {
  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow="Coordinate"
        title="Appointments &amp; Referrals"
        subtitle="Scheduling and referral coordination for people identified by the population rules."
        breadcrumbs={[{ label: "Appointments & Referrals" }]}
        className="mb-8"
      />
      <NotImplementedState
        icon={CalendarClock}
        title="Scheduling views arrive in a later phase"
        description="Appointment books, slot types and referral branches will appear here once their APIs are available."
        roadmap="Appointment status lanes, referral branch graphics and attendance tracking — none of which exist in the backend yet."
      />
    </div>
  );
}
