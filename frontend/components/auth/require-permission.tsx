"use client";

import { roleLabel, useAuth } from "@/lib/auth/auth-context";
import { PermissionNotice } from "@/components/ui/permission-notice";
import { useLocale } from "@/lib/i18n/use-locale";
import type { MessageKey } from "@/lib/i18n/translate";

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
  /** Message key of the workspace name (pages are server components and pass keys). */
  workspace: MessageKey;
  children: React.ReactNode;
}) {
  const { can, state } = useAuth();
  const { t } = useLocale();
  if (can(...anyOf)) return <>{children}</>;
  const role = state.status === "signed_in" ? state.me.role : null;
  return (
    <div className="mx-auto w-full max-w-[1280px] px-4 py-16 sm:px-6 lg:px-8">
      <PermissionNotice
        title={t("access.workspace_unavailable_title", { workspace: t(workspace) })}
        permission={anyOf.reduce((a, b) => t("access.permission_or", { a, b }))}
      >
        {t("access.workspace_unavailable_body", { role: roleLabel(role, t) })}
      </PermissionNotice>
    </div>
  );
}
