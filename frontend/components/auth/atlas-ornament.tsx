/**
 * Decorative survey ornament for the sign-in and access screens. Purely
 * illustrative (aria-hidden): fixed, hand-placed geometry — it depicts no data.
 */
const POINTS: [number, number, number][] = [
  [118, 92, 3.2], [164, 70, 2], [210, 118, 2.6], [96, 160, 1.8], [252, 168, 3.6], [150, 196, 2.2],
  [206, 232, 1.6], [120, 250, 2.8], [276, 236, 2], [232, 292, 2.4], [168, 296, 1.6], [300, 120, 1.6],
  [72, 214, 1.4], [188, 150, 1.4], [318, 196, 2.2], [262, 92, 1.2],
];

export function AtlasOrnament({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 400 380" aria-hidden="true" className={className} fill="none">
      {[150, 112, 74, 36].map((r, i) => (
        <circle
          key={r}
          cx="196"
          cy="190"
          r={r}
          stroke="var(--ink-line)"
          strokeWidth="1"
          strokeDasharray={i % 2 ? "2 6" : undefined}
          className="reveal-fade"
          style={{ "--i": i } as React.CSSProperties}
        />
      ))}
      <path d="M46 190h300M196 40v300" stroke="var(--ink-line)" strokeWidth="0.8" />
      <circle
        cx="196"
        cy="190"
        r="150"
        stroke="var(--ink-accent-2)"
        strokeWidth="1.5"
        strokeDasharray="120 822"
        strokeLinecap="round"
        className="reveal-fade"
        style={{ "--i": 5 } as React.CSSProperties}
      />
      {POINTS.map(([x, y, r], i) => (
        <circle
          key={i}
          cx={x}
          cy={y}
          r={r}
          fill={i % 5 === 0 ? "var(--ink-accent)" : i % 3 === 0 ? "var(--ink-accent-2)" : "var(--ink-muted)"}
          className="reveal-fade"
          style={{ "--i": 6 + i } as React.CSSProperties}
        />
      ))}
    </svg>
  );
}
