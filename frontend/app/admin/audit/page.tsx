import type { Metadata } from "next";
import { AuditAdmin } from "@/components/admin/admin-pages";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";

export const metadata: Metadata = { title: "Audit log" };

export default function Page() {
  return (
    <PageTransition>
      <RequirePermission anyOf={["audit_logs.read"]} workspace="Audit log">
        <AuditAdmin />
      </RequirePermission>
    </PageTransition>
  );
}
