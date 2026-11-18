/**
 * Population Constellation — a deterministic, hand-built SVG field.
 *
 * Each dot is one synthetic person; dots group into cohort "territories"
 * marked by dashed halo rings. There are deliberately NO connecting lines
 * between people: spatial proximity is decorative grouping only and must
 * never be read as a clinical relationship. Layout is seeded, so the field
 * renders identically on every load and on every screen size.
 */

export interface CohortSpec {
  id: string;
  label: string;
  /** Fraction of the field (0–1); resolved against the 160-illustrative-person set. */
  count: number;
  /** Cluster centre in viewBox units (viewBox is 800 × 420). */
  cx: number;
  cy: number;
  /** Scatter radius of the cluster halo. */
  r: number;
  colorVar: string;
}

const W = 800;
const H = 420;

export const COHORTS: CohortSpec[] = [
  {
    id: "ifhas",
    label: "IFHAS — adults programme",
    count: 64,
    cx: 250,
    cy: 180,
    r: 120,
    colorVar: "var(--ink-accent)",
  },
  {
    id: "well-child",
    label: "Well-Child — children programme",
    count: 38,
    cx: 505,
    cy: 130,
    r: 88,
    colorVar: "var(--ink-accent-2)",
  },
  {
    id: "documented-gap",
    label: "Documented gap (illustrative)",
    count: 26,
    cx: 585,
    cy: 295,
    r: 72,
    colorVar: "var(--ink-due)",
  },
  {
    id: "review",
    label: "Clinical review (illustrative)",
    count: 14,
    cx: 395,
    cy: 315,
    r: 52,
    colorVar: "var(--ink-review)",
  },
  {
    id: "history-unavailable",
    label: "History unavailable",
    count: 18,
    cx: 120,
    cy: 320,
    r: 58,
    colorVar: "var(--ink-unknown)",
  },
];

/** Deterministic PRNG so the field never reshuffles between renders. */
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Star {
  x: number;
  y: number;
  r: number;
  o: number;
  c: string;
}

function buildField(): { people: Star[]; dust: Star[] } {
  const rand = mulberry32(0x50524);
  const people: Star[] = [];
  for (const cohort of COHORTS) {
    for (let i = 0; i < cohort.count; i++) {
      // Golden-angle spiral + jitter → even, organic-looking scatter.
      const angle = i * 2.399963 + rand() * 0.5;
      const radius = cohort.r * Math.sqrt((i + 0.5) / cohort.count) * (0.72 + rand() * 0.28);
      people.push({
        x: cohort.cx + Math.cos(angle) * radius * 1.15,
        y: cohort.cy + Math.sin(angle) * radius * 0.8,
        r: 1.6 + rand() * 1.3,
        o: 0.55 + rand() * 0.45,
        c: cohort.colorVar,
      });
    }
  }
  const dust: Star[] = [];
  for (let i = 0; i < 46; i++) {
    dust.push({
      x: rand() * W,
      y: rand() * H,
      r: 0.5 + rand() * 0.9,
      o: 0.15 + rand() * 0.3,
      c: "var(--ink-muted)",
    });
  }
  return { people, dust };
}

const { people: PEOPLE, dust: DUST } = buildField();

export function ConstellationVisualization() {
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Illustrative constellation of the synthetic population. Each point is one synthetic person, grouped into labelled cohort territories. Positions are illustrative and do not represent clinical relationships."
      className="h-full w-full"
      preserveAspectRatio="xMidYMid meet"
    >
      {/* Background dust */}
      {DUST.map((s, i) => (
        <circle key={`d${i}`} cx={s.x} cy={s.y} r={s.r} fill={s.c} opacity={s.o} />
      ))}

      {/* Cohort halo rings — grouping boundaries, not relationships */}
      {COHORTS.map((c) => (
        <g key={c.id}>
          <ellipse
            cx={c.cx}
            cy={c.cy}
            rx={c.r * 1.22}
            ry={c.r * 0.88}
            fill={c.colorVar}
            opacity="0.05"
          />
          <ellipse
            cx={c.cx}
            cy={c.cy}
            rx={c.r * 1.22}
            ry={c.r * 0.88}
            fill="none"
            stroke={c.colorVar}
            strokeWidth="1"
            strokeDasharray="3 6"
            opacity="0.35"
          />
        </g>
      ))}

      {/* One point per synthetic person */}
      {PEOPLE.map((p, i) => (
        <circle key={`p${i}`} cx={p.x} cy={p.y} r={p.r} fill={p.c} opacity={p.o} />
      ))}
    </svg>
  );
}
