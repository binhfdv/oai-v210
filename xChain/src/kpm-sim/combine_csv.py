"""
Combine all CSVs in unicorn_urllc/ into one file.
Usage: python3 combine_csv.py
Output: unicorn_urllc_combined.csv (same directory as this script)
"""
import pandas as pd
from pathlib import Path

INPUT_DIR  = Path(__file__).parent / "unicorn_urllc"
OUTPUT     = Path(__file__).parent / "unicorn_urllc_combined.csv"

files = sorted(INPUT_DIR.glob("*.csv"))
if not files:
    raise SystemExit(f"No CSV files found in {INPUT_DIR}")

chunks = []
for f in files:
    df = pd.read_csv(f)
    chunks.append(df)
    print(f"  {f.name:<30}  {len(df):>7,} rows")

combined = pd.concat(chunks, ignore_index=True)
combined.to_csv(OUTPUT, index=False)
print(f"\nCombined {len(files)} files → {OUTPUT.name}  ({len(combined):,} rows total)")
