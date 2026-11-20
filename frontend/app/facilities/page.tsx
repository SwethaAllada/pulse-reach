import type { Metadata } from "next";
import { FacilityRegister } from "@/components/facilities/facility-register";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";

export const metadata: Metadata = { title: "Facilities" };

export default function FacilitiesPage() {
  return (
    <PageTransition>
      <RequirePermission anyOf={["facilities.read"]} workspace="Facilities">
        <FacilityRegister />
      </RequirePermission>
    </PageTransition>
  );
}
