"""python -m app.services.official_loader [--dry-run] [--report-file PATH]

Exit code: 0 = every unit ingested (or dry-run clean) · 1 = quarantined unit(s) · 2 = fatal, nothing written.
A successful ingestion says nothing about reconciliation: mismatches are reported in the load report.
"""
import argparse
import json
import sys
from pathlib import Path

from . import FatalError, run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="official_loader")
    ap.add_argument("--dry-run", action="store_true", help="verify, parse and validate only; no database needed")
    ap.add_argument("--report-file", type=Path, help="write the full JSON load report here")
    ap.add_argument("--root", type=Path, help="repository root (default: auto-detected)")
    args = ap.parse_args(argv)
    try:
        report = run(root=args.root, dry_run=args.dry_run)
    except FatalError as exc:
        print(f"FATAL (nothing written): {exc}", file=sys.stderr)
        return 2
    if args.report_file:
        args.report_file.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "tables", "quarantined", "post_load_checks") if k in report},
                     indent=2, default=str))
    return 1 if report["quarantined"] else 0


if __name__ == "__main__":
    sys.exit(main())
