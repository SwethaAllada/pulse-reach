import type { Metadata } from "next";
import { AppointmentsWorkspace } from "@/components/coordination/appointments-workspace";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";

export const metadata: Metadata = { title: "Appointments & Referrals" };

export default function AppointmentsPage() {
  return (
    <PageTransition>
      <RequirePermission anyOf={["appointments.read", "referrals.read"]} workspace="nav.appointments_referrals">
        <AppointmentsWorkspace />
      </RequirePermission>
    </PageTransition>
  );
}
