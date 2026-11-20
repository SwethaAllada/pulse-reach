import type { Metadata } from "next";
import { FollowUpWorkspace } from "@/components/coordination/follow-up-workspace";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";

export const metadata: Metadata = { title: "Follow-up" };

export default function FollowUpPage() {
  return (
    <PageTransition>
      <RequirePermission anyOf={["followups.read"]} workspace="Follow-up">
        <FollowUpWorkspace />
      </RequirePermission>
    </PageTransition>
  );
}
