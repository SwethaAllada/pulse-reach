import { createElement, Fragment, type ReactNode } from "react";
import { intlLocale, type Locale } from "./config";
import { en, type MessageKey } from "./messages/en";
import { ar } from "./messages/ar";
import { getLocale } from "./store";

export type { MessageKey };
export type Params = Record<string, string | number>;
/** A bound translator (`useLocale().t` / `useT()`); label helpers take one so render stays hydration-safe. */
export type Translate = (key: MessageKey, params?: Params) => string;

/** Base keys that have plural forms (`<base>.one`, `<base>.other`, … per `Intl.PluralRules`). */
export type PluralKey = { [K in MessageKey]: K extends `${infer B}.other` ? B : never }[MessageKey];

const CATALOGS: Record<Locale, Record<MessageKey, string>> = { en, ar };
const FSI = "\u2068";
const PDI = "\u2069";

/**
 * In Arabic, interpolated values (ids, numbers, Latin names) are wrapped in first-strong isolates
 * so they cannot reorder the surrounding right-to-left sentence (same rule as the backend).
 */
function isolate(value: string | number, locale: Locale): string {
  const s = typeof value === "number" ? value.toLocaleString(intlLocale(locale)) : value;
  return locale === "ar" ? `${FSI}${s}${PDI}` : s;
}

export function translate(locale: Locale, key: MessageKey, params?: Params): string {
  const template = CATALOGS[locale][key] ?? en[key] ?? key;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (m, name: string) => (name in params ? isolate(params[name], locale) : m));
}

export function translatePlural(locale: Locale, key: PluralKey, count: number, params?: Params): string {
  const rule = new Intl.PluralRules(intlLocale(locale)).select(count);
  const k = (`${key}.${rule}` in CATALOGS[locale] ? `${key}.${rule}` : `${key}.other`) as MessageKey;
  return translate(locale, k, { count, ...params });
}

/**
 * A sentence with React nodes in its placeholders (links, emphasis, code). The sentence stays whole
 * per locale; nodes are isolated with `<bdi>` in Arabic.
 */
export function translateRich(locale: Locale, key: MessageKey, nodes: Record<string, ReactNode>): ReactNode[] {
  return translate(locale, key)
    .split(/(\{\w+\})/g)
    .filter((part) => part !== "")
    .map((part, i) => {
      const name = /^\{(\w+)\}$/.exec(part)?.[1];
      if (!name || !(name in nodes)) return part;
      return locale === "ar" ? createElement("bdi", { key: i }, nodes[name]) : createElement(Fragment, { key: i }, nodes[name]);
    });
}

/**
 * Translates with the active locale — for event handlers and async code (errors, notices). Never
 * call it during render: streamed boundaries may hydrate after the locale switched; use the hook.
 */
/** English translator for pure-function tests and English-only contexts (fixtures, logs). */
export const englishT: Translate = (key, params) => translate("en", key, params);

export function t(key: MessageKey, params?: Params): string {
  return translate(getLocale(), key, params);
}

export function tp(key: PluralKey, count: number, params?: Params): string {
  return translatePlural(getLocale(), key, count, params);
}
