"use client";

import { roleLabel, useAuth } from "@/lib/auth/auth-context";
import { PermissionNotice } from "@/components/ui/permission-notice";

/**
 * Renders a workspace only when the signed-in role holds one of `anyOf`. This is a
 * courtesy that avoids a page of 403s; the backend remains the authority, and a
 * view that renders still shows whatever the API refuses as a permission state.
 */
export function RequirePermission({
  anyOf,
  workspace,
  children,
}: {
  anyOf: string[];
  workspace: string;
  children: React.ReactNode;
}) {
  const { can, state } = useAuth();
  if (can(...anyOf)) return <>{children}</>;
  const role = state.status === "signed_in" ? state.me.role : null;
  return (
    <div className="mx-auto w-full max-w-[1280px] px-4 py-16 sm:px-6 lg:px-8">
      <PermissionNotice title={`${workspace} is not available for your role`} permission={anyOf.join(" or ")}>
        Signed in as {roleLabel(role)}. Your organization administrator can change your role or access if you need this
        workspace.
      </PermissionNotice>
    </div>
  );
}
