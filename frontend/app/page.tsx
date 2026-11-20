import { Suspense } from "react";
import { RoleHome } from "@/components/home/role-home";
import { PageTransition } from "@/components/ui/page-transition";

export default function HomePage() {
  return (
    <PageTransition>
      <Suspense fallback={<div aria-busy="true" aria-label="Loading your workspace" className="skeleton h-[640px] w-full" />}>
        <RoleHome />
      </Suspense>
    </PageTransition>
  );
}
