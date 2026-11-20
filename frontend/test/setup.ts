import { beforeEach } from "vitest";
import { allowUnauthenticatedRequests, releaseRequests } from "@/lib/api/client";
import { resetSessionCache, setSession } from "@/lib/auth/session";
import { resetLocaleForTests } from "@/lib/i18n/store";

/*
 * Every test starts as a signed-in staff tab: the API client refuses data requests without an
 * access token, exactly as in the app. Authentication suites clear the session themselves.
 */
beforeEach(() => {
  window.sessionStorage.clear();
  resetSessionCache();
  resetLocaleForTests();
  allowUnauthenticatedRequests(false);
  releaseRequests();
  setSession({ access_token: "pra_test", refresh_token: "prr_test", expires_in: 900 });
});
