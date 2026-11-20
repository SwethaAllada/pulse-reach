import type { Metadata } from "next";
import { UsersAdmin } from "@/components/admin/admin-pages";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";

export const metadata: Metadata = { title: "Users & roles" };

export default function Page() {
  return (
    <PageTransition>
      <RequirePermission anyOf={["users.read"]} workspace="Users & roles">
        <UsersAdmin />
      </RequirePermission>
    </PageTransition>
  );
}
