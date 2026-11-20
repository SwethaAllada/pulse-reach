"""Small-cell suppression applied whenever aggregates leave the backend.

- Primary: a count `n` with `0 < n < k` (`POPULATION_MIN_CELL_SIZE`, default 5) is returned as
  `null` and listed in `suppressed`. Zero is shown. An area whose population is below `k` has
  every count suppressed.
- Cohorts: a cohort cell is also suppressed when its complementary cohort (adults/children,
  female/male) is small, so `all - cohort` cannot reveal it.
- Complementary (differencing guard): a parent equals the sum of its members (districts of the
  state; local areas of a district plus the district's remainder of people without a recorded
  local area). Whenever a group contains a sensitive cell (small or suppressed, including a small
  remainder) but only one unknown cell, the smallest other non-zero member is suppressed too,
  repeated until stable; likewise when several cells are unknown but their total (parent minus the
  visible members) is itself small. The remainder is "known" only where it is published (the population
  remainder, or zero when a district has no people without a local area).
- Derived values (prevalence, change, coverage) are suppressed when any input is. Trend
  direction and hotspot class stay visible (they only disclose the sign of a thresholded change).

Every endpoint uses the same deterministic rules, so repeated filtering yields the same pattern.
Residual risk (documented): differences between nested time windows are not cross-suppressed.
"""

from __future__ import annotations

from functools import cached_property
from typing import Any

from app.services.population.vocabulary import COMPLEMENTARY_COHORTS

POPULATION_PATH = ("population", "all")


def _get(d: Any, path: tuple) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


class Suppressor:
    def __init__(self, snapshot: dict[str, Any], k: int) -> None:
        self.areas = snapshot["areas"]
        self.k = k
        self._cache: dict[tuple, tuple[frozenset[str], frozenset[str]]] = {}

    def small(self, n: Any) -> bool:
        return _int(n) and 0 < n < self.k

    @cached_property
    def _groups(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for aid, e in sorted(self.areas.items()):
            if e["population"] is not None and e["area"]["level"] in ("district", "local_area"):
                groups.setdefault(e["area"]["parent_area_id"], []).append(aid)
        return {p: m for p, m in groups.items() if p in self.areas}

    @cached_property
    def small_areas(self) -> frozenset[str]:
        return frozenset(a for a, e in self.areas.items() if self.small(_get(e, POPULATION_PATH)))

    def _compute(self, path: tuple) -> tuple[frozenset[str], frozenset[str]]:
        raw = {a: _get(e, path) for a, e in self.areas.items()}
        hidden = {a for a, v in raw.items() if a in self.small_areas or self.small(v)}
        ci = next((i for i, p in enumerate(path) if p in COMPLEMENTARY_COHORTS), None)
        if ci is not None:
            comp = path[:ci] + (COMPLEMENTARY_COHORTS[path[ci]],) + path[ci + 1:]
            hidden |= {a for a, e in self.areas.items() if self.small(_get(e, comp))}
        hidden_remainders: set[str] = set()
        changed = True
        while changed:
            changed = False
            for parent, members in self._groups.items():
                vals = [raw[m] for m in members]
                rem = raw[parent] - sum(vals) if _int(raw[parent]) and all(_int(v) for v in vals) else None
                published_zero = self.areas[parent].get("unassigned_local_area_population") == 0
                rem_known = (path == POPULATION_PATH or published_zero) and parent not in hidden_remainders
                rem_unknown = rem is not None and rem != 0 and not rem_known
                sensitive = any(m in hidden for m in members) or self.small(rem)
                unknowns = sum(m in hidden for m in members) + (rem_unknown or (self.small(rem) and not rem_known)) \
                    + (parent in hidden)
                if self.small(rem) and path == POPULATION_PATH and parent not in hidden_remainders:
                    hidden_remainders.add(parent)  # the published remainder itself is small
                    changed = True
                    continue
                # Several unknowns protect each other only when their published total is not small
                # itself (parent − visible members); otherwise each is bounded to 1…k−1.
                hidden_total = (
                    sum(raw[m] for m in members if m in hidden) + (rem if rem_unknown else 0)
                    if rem is not None and parent not in hidden else None
                )
                if not sensitive or (unknowns >= 2 and not self.small(hidden_total)):
                    continue
                candidates = [(raw[m], m) for m in members if m not in hidden and _int(raw[m]) and raw[m] > 0]
                if path == POPULATION_PATH and parent not in hidden_remainders and _int(rem) and rem > 0:
                    candidates.append((rem, f"{parent}#remainder"))
                if not candidates:
                    continue
                _, extra = min(candidates)
                if extra.endswith("#remainder"):
                    hidden_remainders.add(parent)
                else:
                    hidden.add(extra)
                changed = True
        return frozenset(hidden), frozenset(hidden_remainders)

    def hidden(self, path: tuple) -> frozenset[str]:
        """Area ids whose value at `path` (relative to an area entry) must be suppressed."""
        if path not in self._cache:
            self._cache[path] = self._compute(path)
        return self._cache[path][0]

    def remainder_hidden(self, area_id: str) -> bool:
        """Whether a district's 'no recorded local area' population must be suppressed."""
        if POPULATION_PATH not in self._cache:
            self._cache[POPULATION_PATH] = self._compute(POPULATION_PATH)
        return area_id in self._cache[POPULATION_PATH][1]

    def value(self, area_id: str, path: tuple) -> Any:
        return None if area_id in self.hidden(path) else _get(self.areas[area_id], path)

    def counts(self, area_id: str, base: tuple, fields: tuple[str, ...]) -> tuple[dict[str, Any], list[str]]:
        """Copy of the block at `base` with each count in `fields` suppressed as required."""
        block = dict(_get(self.areas[area_id], base) or {})
        suppressed = []
        for f in fields:
            if area_id in self.hidden(base + (f,)):
                block[f] = None
                suppressed.append(f)
        return block, suppressed

    def primary(self, metrics: dict[str, Any], fields: tuple[str, ...]) -> tuple[dict[str, Any], list[str]]:
        out, suppressed = dict(metrics), []
        for f in fields:
            if self.small(out.get(f)):
                out[f] = None
                suppressed.append(f)
        return out, suppressed
