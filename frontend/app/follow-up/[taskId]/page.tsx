import type { Metadata } from "next";
import { Suspense } from "react";
import { TaskDetailPage } from "@/components/coordination/task-detail";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";
import { LoadingState } from "@/components/ui/loading-state";

export const metadata: Metadata = { title: "Follow-up" };

export default function FollowUpTaskPage() {
  return (
    <PageTransition>
      <Suspense
        fallback={
          <div className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-6 lg:px-8">
            <LoadingState rows={6} />
          </div>
        }
      >
        <RequirePermission anyOf={["followups.read"]} workspace="Follow-up">
          <TaskDetailPage />
        </RequirePermission>
      </Suspense>
    </PageTransition>
  );
}
