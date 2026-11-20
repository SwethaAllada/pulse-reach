import type { Metadata } from "next";
import { PatientLinksAdmin } from "@/components/admin/admin-pages";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";

export const metadata: Metadata = { title: "Patient portal links" };

export default function Page() {
  return (
    <PageTransition>
      <RequirePermission anyOf={["patient_links.manage"]} workspace="nav.patient_portal_links">
        <PatientLinksAdmin />
      </RequirePermission>
    </PageTransition>
  );
}
