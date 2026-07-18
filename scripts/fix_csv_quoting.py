"""
Fix CSV files that have unquoted fields with commas.

This script reads existing evaluation CSV files and rewrites them with proper
quoting so they can be opened correctly in Excel/Google Sheets.

Usage:
    python scripts/fix_csv_quoting.py data/eval/results/eval_detailed_20251219_014851.csv
    python scripts/fix_csv_quoting.py data/eval/results/ --all
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

try:
    import pandas as pd

    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    print("Warning: pandas not available. Install with: pip install pandas")


def fix_csv_file(csv_path: Path) -> None:
    """Fix a single CSV file by rewriting it with proper quoting."""
    print(f"Fixing: {csv_path}")

    # Create backup first
    backup_path = csv_path.with_suffix(csv_path.suffix + ".backup")
    if backup_path.exists():
        print(f"  Backup already exists, skipping: {csv_path}")
        return

    print(f"  Creating backup: {backup_path}")
    import shutil

    shutil.copy2(csv_path, backup_path)

    # Read the CSV - try pandas first (handles malformed CSVs better)
    if HAS_PANDAS:
        try:
            # pandas can handle malformed CSVs with multi-line fields
            df = pd.read_csv(csv_path, encoding="utf-8", quotechar='"', on_bad_lines="skip")
            # Write back with proper quoting
            df.to_csv(csv_path, index=False, quoting=csv.QUOTE_ALL, encoding="utf-8")
            print(f"  [OK] Fixed with pandas: {csv_path}")
            print(f"  Backup saved: {backup_path}")
            return
        except Exception as e:
            print(f"  pandas failed: {e}, trying manual parsing...")

    # Fallback: manual parsing with csv module
    rows = []
    try:
        with open(csv_path, encoding="utf-8", newline="") as f:
            # Use csv.Sniffer to detect dialect, then read
            sample = f.read(1024)
            f.seek(0)
            sniffer = csv.Sniffer()
            dialect = sniffer.sniff(sample)
            reader = csv.reader(f, dialect=dialect)
            for row in reader:
                rows.append(row)
    except Exception as e:
        print(f"  Error reading CSV: {e}")
        print("  Cannot fix this file automatically. Please check the format.")
        return

    if not rows:
        print(f"  Warning: No data found in {csv_path}")
        return

    # Write with proper quoting
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        for row in rows:
            writer.writerow(row)

    print(f"  [OK] Fixed: {csv_path}")
    print(f"  Backup saved: {backup_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix CSV files with unquoted fields containing commas"
    )
    parser.add_argument(
        "path",
        type=str,
        help="Path to CSV file or directory containing CSV files",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Fix all CSV files in the directory",
    )

    args = parser.parse_args()

    path = Path(args.path)

    if not path.exists():
        print(f"Error: Path does not exist: {path}")
        sys.exit(1)

    if path.is_file():
        # Fix single file
        if path.suffix.lower() != ".csv":
            print(f"Error: Not a CSV file: {path}")
            sys.exit(1)
        fix_csv_file(path)
    elif path.is_dir():
        # Fix directory
        if args.all:
            csv_files = list(path.glob("*.csv"))
            if not csv_files:
                print(f"No CSV files found in {path}")
                sys.exit(0)
            print(f"Found {len(csv_files)} CSV file(s)")
            for csv_file in csv_files:
                fix_csv_file(csv_file)
                print()
        else:
            print("Error: Directory provided but --all flag not set.")
            print("Use --all to fix all CSV files in the directory.")
            sys.exit(1)
    else:
        print(f"Error: Invalid path: {path}")
        sys.exit(1)

    print("\nDone!")


if __name__ == "__main__":
    main()
