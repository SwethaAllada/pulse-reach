import type { Metadata } from "next";
import { AssignmentsAdmin } from "@/components/admin/admin-pages";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";

export const metadata: Metadata = { title: "Care-team assignments" };

export default function Page() {
  return (
    <PageTransition>
      <RequirePermission anyOf={["assignments.manage"]} workspace="Care-team assignments">
        <AssignmentsAdmin />
      </RequirePermission>
    </PageTransition>
  );
}
