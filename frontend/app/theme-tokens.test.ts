import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Guards the "Prevention Atlas" colour system: both themes define the same semantic tokens,
 * keep the teal + coral brand, avoid a blue-led interaction colour and meet WCAG AA for the
 * pairs the interface actually renders.
 */
const ROOT = join(__dirname, "..");
const css = readFileSync(join(__dirname, "globals.css"), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("\n}", start));
  return Object.fromEntries([...body.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}

const light = block(':root,\n[data-theme="light"] {');
const dark = block('[data-theme="dark"] {');
const themes = { light, dark } as const;

function rgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}
function luminance(hex: string): number {
  const [r, g, b] = rgb(hex).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
function hue(hex: string): number {
  const [r, g, b] = rgb(hex).map((v) => v / 255);
  const max = Math.max(r, g, b);
  const d = max - Math.min(r, g, b);
  if (d === 0) return 0;
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return (h * 60 + 360) % 360;
}

const SEMANTIC = [
  "background",
  "surface-primary",
  "surface-secondary",
  "surface-elevated",
  "surface-brand",
  "brand-primary",
  "brand-secondary",
  "accent-primary",
  "accent-secondary",
  "accent-warm",
  "text-primary",
  "text-secondary",
  "border-subtle",
  "interactive-hover",
  "interactive-active",
  "focus-ring",
  "success",
  "warning",
  "danger",
];

describe("design tokens", () => {
  it("defines every semantic token in both themes, and the same token set", () => {
    for (const t of Object.values(themes)) for (const name of SEMANTIC) expect(t[name], name).toBeTruthy();
    expect(Object.keys(dark).sort()).toEqual(Object.keys(light).sort());
  });

  it("uses the specified light palette", () => {
    expect(light).toMatchObject({
      background: "#f5f0e6",
      "surface-secondary": "#eae5da",
      "surface-elevated": "#fffcf5",
      "brand-primary": "#0d4945",
      "brand-secondary": "#174f49",
      "accent-warm": "#f0785b",
      "text-primary": "#18302e",
      "border-subtle": "#d8d3c8",
    });
  });

  it("uses the specified dark palette", () => {
    expect(dark).toMatchObject({
      background: "#0b132b",
      "surface-elevated": "#1c2541",
      "surface-secondary": "#15203a",
      "surface-brand": "#153b3a",
      "accent-primary": "#2ec4b6",
      "accent-warm": "#f18b70",
      "text-primary": "#f8fafc",
      "text-secondary": "#94a3b8",
      "border-subtle": "#33415c",
    });
  });

  it.each(Object.entries(themes))("%s keeps a teal primary interaction and a coral brand accent", (_, t) => {
    // Teal/seafoam (~165-185°), never the blue SaaS default (~200-250°).
    expect(hue(t["accent-primary"])).toBeGreaterThan(160);
    expect(hue(t["accent-primary"])).toBeLessThan(190);
    expect(hue(t["focus-ring"])).toBeLessThan(190);
    expect(hue(t["brand-primary"])).toBeGreaterThan(160);
    expect(hue(t["brand-primary"])).toBeLessThan(190);
    // Coral (~5-20°) — saturated, not a desaturated brown.
    expect(hue(t["accent-warm"])).toBeLessThan(20);
    const [r, , b] = rgb(t["accent-warm"]);
    expect(r - b).toBeGreaterThan(110);
    // The brand surface (logo, avatar) is deep teal in both themes.
    expect(hue(t["surface-brand"])).toBeGreaterThan(160);
    expect(hue(t["surface-brand"])).toBeLessThan(190);
  });

  it("has no full-bleed coloured plate: the feature surface is the card surface", () => {
    expect(css).toMatch(/--ink: var\(--surface-elevated\)/);
    for (const t of Object.values(themes)) expect(t.ink).toBeUndefined();
  });

  it("does not use coral as danger or teal as success", () => {
    for (const t of Object.values(themes)) {
      expect(t.danger).not.toBe(t["accent-warm"]);
      expect(t.success).not.toBe(t["accent-primary"]);
    }
  });

  const AA: [string, string, number][] = [
    ["text-primary", "background", 4.5],
    ["text-primary", "surface-elevated", 4.5],
    ["text-secondary", "background", 4.5],
    ["text-secondary", "surface-secondary", 4.5],
    ["text-secondary", "surface-elevated", 4.5],
    ["text-tertiary", "surface-elevated", 4.5],
    ["accent-primary", "background", 4.5],
    ["accent-primary", "surface-elevated", 4.5],
    ["on-accent-primary", "accent-primary", 4.5],
    ["on-accent-warm", "accent-warm", 4.5],
    ["accent-warm-text", "background", 4.5],
    ["accent-warm-text", "surface-secondary", 4.5],
    ["accent-secondary", "surface-elevated", 4.5],
    ["danger", "surface-elevated", 4.5],
    ["status-due", "background", 4.5],
    ["status-upcoming", "surface-secondary", 4.5],
    ["status-insufficient", "surface-secondary", 4.5],
    ["status-completed", "surface-secondary", 4.5],
    ["on-brand", "surface-brand", 4.5],
    ["focus-ring", "background", 3],
    ["border-strong", "surface-elevated", 3],
  ];
  it.each(Object.entries(themes))("%s meets WCAG AA for rendered pairs", (_, t) => {
    for (const [fg, bg, min] of AA) expect(contrast(t[fg], t[bg]), `${fg} on ${bg}`).toBeGreaterThanOrEqual(min);
  });

  it("keeps theme-specific colours out of components", () => {
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const p = join(dir, name);
        if (statSync(p).isDirectory()) walk(p);
        else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) files.push(p);
      }
    };
    ["components", "lib", "app"].forEach((d) => walk(join(ROOT, d)));
    const offenders = files.filter((f) => /#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?![\w-])|rgba?\(/.test(readFileSync(f, "utf8")));
    expect(offenders.map((f) => f.slice(ROOT.length + 1))).toEqual([]);
  });
});
