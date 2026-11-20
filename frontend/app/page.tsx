import { Suspense } from "react";
import { RoleHome } from "@/components/home/role-home";
import { PageTransition } from "@/components/ui/page-transition";
import { BusyBlock } from "@/components/ui/busy-block";

export default function HomePage() {
  return (
    <PageTransition>
      <Suspense fallback={<BusyBlock labelKey="page.loading_workspace" className="skeleton h-[640px] w-full" />}>
        <RoleHome />
      </Suspense>
    </PageTransition>
  );
}
