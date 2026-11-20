import type { Metadata } from "next";
import { PopulationAdmin } from "@/components/admin/admin-pages";
import { RequirePermission } from "@/components/auth/require-permission";
import { PageTransition } from "@/components/ui/page-transition";

export const metadata: Metadata = { title: "Population aggregation" };

export default function Page() {
  return (
    <PageTransition>
      <RequirePermission anyOf={["population.configure", "population.refresh"]} workspace="nav.population_aggregation">
        <PopulationAdmin />
      </RequirePermission>
    </PageTransition>
  );
}
