"use client";

import { useCallback } from "react";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/auth-context";
import { isLocale, LOCALE_UNSYNCED_KEY as UNSYNCED_KEY, type Locale } from "./config";
import { applyLocale, getLocale } from "./store";

/*
 * Language persistence:
 * - every choice is stored in this browser (localStorage) and applied immediately;
 * - signed in, it is also saved to the account (`PATCH /me/preferences`);
 * - a choice made while signed out (or whose save failed) is marked unsynced and saved to the
 *   account at the next sign-in; otherwise the account's saved preference wins at sign-in.
 */

function markUnsynced(value: boolean): void {
  try {
    if (value) localStorage.setItem(UNSYNCED_KEY, "1");
    else localStorage.removeItem(UNSYNCED_KEY);
  } catch {
    /* ignore */
  }
}

function isUnsynced(): boolean {
  try {
    return localStorage.getItem(UNSYNCED_KEY) === "1";
  } catch {
    return false;
  }
}

async function save(locale: Locale): Promise<void> {
  try {
    await api.updatePreferences({ preferred_language: locale });
    markUnsynced(false);
  } catch {
    // Kept locally; retried at the next sign-in. Never signs the user out.
    markUnsynced(true);
  }
}

/** Reconciles the browser language with the account's preference once per signed-in identity. */
export function reconcileSignedInLocale(accountPreference: string | null | undefined): void {
  if (isUnsynced()) {
    void save(getLocale());
    return;
  }
  if (isLocale(accountPreference)) applyLocale(accountPreference);
}

/** Changes the UI language without navigating, remounting or touching the session. */
export function useChangeLanguage(): (locale: Locale) => void {
  const { state } = useAuth();
  const signedIn = state.status === "signed_in";
  return useCallback(
    (locale: Locale) => {
      if (locale === getLocale()) return;
      applyLocale(locale);
      if (signedIn) void save(locale);
      else markUnsynced(true);
    },
    [signedIn]
  );
}
