"""Compatibility wrapper for rebuilding selected companies with the canonical CLI."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild selected tickers using scripts/build_index.py."
    )
    parser.add_argument(
        "--ticker",
        action="append",
        required=True,
        help="Ticker symbol. Repeat the option for multiple companies.",
    )
    parser.add_argument("--period", help="Optional period such as Q3-2025.")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Replace the collection before indexing the selected corpus.",
    )
    args = parser.parse_args()

    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "build_index.py")]
    for ticker in args.ticker:
        command.extend(("--ticker", ticker))
    if args.period:
        command.extend(("--period", args.period))
    if args.fresh:
        command.append("--fresh")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


if __name__ == "__main__":
    main()
