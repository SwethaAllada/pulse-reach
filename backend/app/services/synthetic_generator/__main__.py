"""CLI entry point for `python -m app.services.synthetic_generator`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.clinical_loader.parse import repo_root
from app.services.synthetic_generator.generator import (
    generate_synthetic_dataset,
    write_data_card,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PulseReach synthetic patient dataset.")
    parser.add_argument("--seed", type=int, default=20261116)
    parser.add_argument("--patients", type=int, default=550)
    args = parser.parse_args()

    ds = generate_synthetic_dataset(seed=args.seed, total_patients=args.patients)
    card_path = repo_root() / ds.generation_run["data_card_path"]
    write_data_card(ds, card_path)
    print(
        json.dumps(
            {
                "run_id": ds.generation_run["run_id"],
                "seed": args.seed,
                "patients": len(ds.patients),
                "evaluations": len(ds.eligibility_evaluations),
                "care_gaps": len(ds.care_gaps),
                "data_card_path": str(card_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
