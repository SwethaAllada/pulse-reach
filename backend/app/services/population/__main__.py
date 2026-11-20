"""Scheduled aggregation entry point (cron / Cloud Scheduler job), `DATA_SOURCE=db`:

    python -m app.services.population refresh            # every active organization
    python -m app.services.population refresh --org <organization_id>

Exit codes: 0 = all refreshed (or already running elsewhere) · 2 = at least one failure.
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh population-intelligence aggregates.")
    sub = parser.add_subparsers(dest="command", required=True)
    ref = sub.add_parser("refresh")
    ref.add_argument("--org", action="append", help="organization id (repeatable); default: all active")
    args = parser.parse_args(argv)

    from app.models.identity import Organization
    from app.services.identity.store import identity_session
    from app.services.population.service import RefreshInProgress, get_population_service

    orgs = args.org
    if not orgs:
        with identity_session() as s:
            orgs = list(s.scalars(select(Organization.organization_id).where(Organization.is_active)))
    svc, failed, report = get_population_service(), 0, {}
    for org in orgs:
        try:
            run = svc.refresh(org, trigger="scheduled")
            report[org] = {"run_id": run["run_id"], "summary": run["summary"]}
        except RefreshInProgress:
            report[org] = {"skipped": "aggregation already running"}
        except Exception as exc:  # reported, other organizations still refresh
            failed += 1
            report[org] = {"failed": type(exc).__name__}
    print(json.dumps(report, indent=2, default=str))
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
