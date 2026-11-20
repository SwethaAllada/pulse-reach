"use client";

import { useEffect, useRef, useState } from "react";

/**
 * A count that eases from its previous value to the new one when it changes (filters, refetch).
 * The first paint shows the real value; reduced motion (or no animation support) jumps straight to it.
 * Only whole-number counts animate — never rates or clinical values.
 */
export function AnimatedNumber({ value }: { value: number }) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);

  useEffect(() => {
    const start = from.current;
    from.current = value;
    if (start === value) return;
    const reduce = typeof window.matchMedia !== "function" || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || typeof requestAnimationFrame !== "function") {
      const id = setTimeout(() => setShown(value), 0);
      return () => clearTimeout(id);
    }
    const t0 = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / 480);
      const eased = 1 - (1 - k) ** 3;
      setShown(Math.round(start + (value - start) * eased));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return <>{shown.toLocaleString("en")}</>;
}
