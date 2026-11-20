"""Programme summary (`GET /api/v1/programmes/{pathway}/summary`): pure aggregation + privacy.

Inputs come from the read repository (memory and PostgreSQL use the same definitions):
- `members`: (patient_id, history_status) for everyone with a history record for the programme in
  the caller's patient scope after the region/sex/age filters — the same set as
  `GET /patients?pathway=…` with those filters.
- `gaps`: (patient_id, gap_type, status, identified_date, closed_date) — care-gap records under the
  programme's rules, for those members only.
- `eligibility`: the dashboard's per-pathway breakdown computed over the members only.
- `evaluation_dates`: reference dates of the persisted evaluation runs.

Segments are mutually exclusive: an open gap under the programme's rules takes precedence,
otherwise the person's history status for the programme decides. Eligibility (in-band evaluation
results), recorded gaps, documented completions and missing history are reported separately and
are never substituted for one another.

Trend: care-gap records only exist where an evaluation ran, so a period comparison is reported
only when persisted evaluation runs cover the previous window. Otherwise the previous-window
counts are `null` (not observed, never zero) and the direction is `INSUFFICIENT_DATA` with reason
`evaluation_history_incomplete`.

Privacy (`POPULATION_MIN_CELL_SIZE` = k): a count with 0 < n < k is `null` and listed in
`suppressed`; when a partition with a published total (history, segments, gap statuses, open-gap
types) would hide exactly one cell, its smallest other non-zero cell is hidden too; a member set
below k suppresses every count.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Any, Iterable

from app.services.population.config import TrendThresholds
from app.services.population.engine import classify_trend, windows
from app.services.population.vocabulary import PERIODS

SEGMENTS = ("open_gap", "available", "partial", "not_available")
HISTORY = ("available", "partial", "not_available")
GAP_STATUSES = ("open", "closed_completed", "closed_refused", "suppressed", "superseded")
GAP_TYPES = (
    "no_documented_screening",
    "interval_elapsed",
    "partial_completion",
    "referral_not_initiated",
    "visit_not_attended",
)
ELIGIBILITY = (
    "programme_eligible_patients",
    "due_or_upcoming_patients",
    "review_flagged_patients",
    "rule_review_patients",
)

DISCLAIMER = (
    "Aggregates of synthetic records for your patient scope, computed by the backend from the latest "
    "evaluation run. Counts are not clinical outcomes; missing history is not evidence of missed care."
)

Member = tuple[str, str]
Gap = tuple[str, str, str, date, date | None]


def _small(n: int | None, k: int) -> bool:
    return n is not None and 0 < n < k


def _partition(values: dict[str, int], k: int, parent_published: bool) -> set[str]:
    """Keys to hide: small cells, plus one more when a single hidden cell could be derived."""
    hidden = {key for key, n in values.items() if _small(n, k)}
    if parent_published and len(hidden) == 1:
        rest = sorted((n, key) for key, n in values.items() if key not in hidden and n > 0)
        if rest:
            hidden.add(rest[0][1])
    return hidden


def _trend(gaps: list[Gap], evaluation_dates: Iterable[date], as_of: date, period: str,
           population: int) -> dict[str, Any]:
    w = windows(as_of, PERIODS[period])
    current_start = w["current_after"] + timedelta(days=1)
    previous_start = w["previous_after"] + timedelta(days=1)
    dates = sorted(set(evaluation_dates))
    evidence_start = dates[0] if dates else None
    covered = evidence_start is not None and evidence_start <= previous_start

    def identified(after: date, end: date) -> int:
        return sum(1 for g in gaps if after < g[3] <= end)

    def completed(after: date, end: date) -> int:
        return sum(1 for g in gaps if g[2] == "closed_completed" and g[4] is not None and after < g[4] <= end)

    cur_identified = identified(w["current_after"], w["current_end"])
    cur_completed = completed(w["current_after"], w["current_end"])
    prev_identified = identified(w["previous_after"], w["previous_end"]) if covered else None
    prev_completed = completed(w["previous_after"], w["previous_end"]) if covered else None
    if covered:
        trend = classify_trend(cur_identified, prev_identified, population=population, history_complete=True,
                               completeness=None, cfg=TrendThresholds())
    else:
        trend = {"direction": "INSUFFICIENT_DATA", "reason_codes": ["evaluation_history_incomplete"],
                 "absolute_change": None, "percentage_change": None}
    return {
        "period": period,
        "current_start": current_start,
        "current_end": w["current_end"],
        "previous_start": previous_start,
        "previous_end": w["previous_end"],
        "evaluation_runs": len(dates),
        "evaluation_history_start": evidence_start,
        "previous_period_observed": covered,
        "care_gaps_identified": cur_identified,
        "previous_care_gaps_identified": prev_identified,
        "gaps_closed_completed": cur_completed,
        "previous_gaps_closed_completed": prev_completed,
        "care_gap_trend": trend,
    }


def build_programme_summary(
    *,
    pathway: str,
    members: list[Member],
    gaps: list[Gap],
    eligibility: dict[str, int],
    evaluation_dates: Iterable[date],
    evaluation_run_id: str,
    reference_date: date,
    patient_scope: str,
    filters: dict[str, Any],
    period: str,
    min_cell_size: int,
) -> dict[str, Any]:
    k = min_cell_size
    member_ids = {pid for pid, _ in members}
    gaps = [g for g in gaps if g[0] in member_ids]
    open_people = {g[0] for g in gaps if g[2] == "open"}

    history = {h: 0 for h in HISTORY}
    segments = {s: 0 for s in SEGMENTS}
    for pid, hst in members:
        history[hst] += 1
        segments["open_gap" if pid in open_people else hst] += 1
    statuses = Counter(g[2] for g in gaps)
    care_gaps = {s: statuses.get(s, 0) for s in GAP_STATUSES}
    total_gaps = len(gaps)
    types = Counter(g[1] for g in gaps if g[2] == "open")
    open_by_type = {t: types.get(t, 0) for t in GAP_TYPES}
    elig = {key: int(eligibility.get(key, 0)) for key in ELIGIBILITY}
    trend = _trend(gaps, evaluation_dates, reference_date, period, len(members))

    suppressed: list[str] = []
    n_members: int | None = len(members)
    if _small(n_members, k):
        # Too few people for any aggregate: nothing but the fact of suppression leaves the backend.
        n_members = None
        suppressed.append("all")
        history = dict.fromkeys(history)
        segments = dict.fromkeys(segments)
        care_gaps = dict.fromkeys(care_gaps)
        total_gaps = None
        open_by_type = dict.fromkeys(open_by_type)
        elig = dict.fromkeys(elig)
        for key in ("care_gaps_identified", "previous_care_gaps_identified", "gaps_closed_completed",
                    "previous_gaps_closed_completed"):
            trend[key] = None
        trend["care_gap_trend"] = {**trend["care_gap_trend"], "absolute_change": None, "percentage_change": None}
    else:
        def hide(name: str, values: dict[str, int], parent_published: bool) -> dict[str, int | None]:
            keys = _partition(values, k, parent_published)
            suppressed.extend(f"{name}.{key}" for key in sorted(keys))
            return {key: (None if key in keys else n) for key, n in values.items()}

        history = hide("history", history, True)
        segments = hide("segments", segments, True)
        if _small(total_gaps, k):
            suppressed.append("care_gaps.total")
            total_gaps = None
        care_gaps = hide("care_gaps", care_gaps, total_gaps is not None)
        open_by_type = hide("open_gaps_by_type", open_by_type, care_gaps["open"] is not None)
        elig = hide("eligibility", elig, False)
        trend_keys = ("care_gaps_identified", "previous_care_gaps_identified", "gaps_closed_completed",
                      "previous_gaps_closed_completed")
        for key in trend_keys:
            if _small(trend[key], k):
                trend[key] = None
                suppressed.append(f"trend.{key}")
        if trend["care_gaps_identified"] is None or (
                trend["previous_period_observed"] and trend["previous_care_gaps_identified"] is None):
            trend["care_gap_trend"] = {**trend["care_gap_trend"], "absolute_change": None, "percentage_change": None}

    return {
        "is_synthetic": True,
        "pathway": pathway,
        "evaluation_run_id": evaluation_run_id,
        "reference_date": reference_date,
        "patient_scope": patient_scope,
        "filters": filters,
        "min_cell_size": k,
        "members": n_members,
        "history": history,
        "segments": [{"segment": s, "people": segments[s]} for s in SEGMENTS],
        "people_with_open_gap": segments["open_gap"],
        "care_gaps": {**care_gaps, "total": total_gaps},
        "open_gaps_by_type": open_by_type,
        "eligibility": elig,
        "trend": trend,
        "suppressed": suppressed,
        "disclaimer": DISCLAIMER,
    }
