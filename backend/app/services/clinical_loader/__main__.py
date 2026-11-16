"""CLI entry point: `python -m app.services.clinical_loader`."""

import json
from dataclasses import asdict

from .load import run


def main() -> None:
    summary = run()
    print(json.dumps(asdict(summary), indent=2))


if __name__ == "__main__":
    main()
