"""
Combine KPI CSVs from 'KPIs (After Colosseum)' grouped by (slice, application).
One output CSV is written per group, e.g.:
  output/urllc_Teams.csv
  output/urllc_Twitch.csv
  output/urllc_Zoom.csv
  ...

The slice type comes from the filename prefix (urllc / mmtc / embb / ar).
The application label comes from file_app_mapping.csv.
Files not in the mapping are skipped with a warning.
Empty/unnamed columns (artefacts of double-comma headers) are dropped.
"""

import sys
import pandas as pd
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
KPI_DIR     = SCRIPT_DIR / "KPIs (After Colosseum)"
MAPPING_CSV = SCRIPT_DIR / "file_app_mapping.csv"
OUTPUT_DIR  = SCRIPT_DIR / "output"


def load_mapping(path: Path) -> dict:
    df = pd.read_csv(path)
    return dict(zip(df["file"], df["app"]))


def load_kpi(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    df = df.loc[:, df.columns != ""]
    return df


def main():
    mapping   = load_mapping(MAPPING_CSV)
    csv_files = sorted(KPI_DIR.glob("*.csv"))

    if not csv_files:
        sys.exit(f"No CSV files found in {KPI_DIR}")

    OUTPUT_DIR.mkdir(exist_ok=True)

    # accumulate rows per (slice, application) group
    groups: dict[tuple, list] = {}
    skipped = []

    for csv_path in csv_files:
        stem       = csv_path.stem               # e.g. urllc_305
        app        = mapping.get(stem)
        if app is None:
            skipped.append(stem)
            continue

        slice_type = stem.split("_")[0]          # e.g. urllc
        key        = (slice_type, app)

        df = load_kpi(csv_path)
        groups.setdefault(key, []).append(df)

    if skipped:
        print(f"Skipped {len(skipped)} files not in mapping: "
              f"{skipped[:5]}{'...' if len(skipped) > 5 else ''}")

    if not groups:
        sys.exit("No files matched the mapping — nothing to combine.")

    for (slice_type, app), chunks in sorted(groups.items()):
        combined  = pd.concat(chunks, ignore_index=True)
        out_path  = OUTPUT_DIR / f"{slice_type}_{app}.csv"
        combined.to_csv(out_path, index=False)
        print(f"  {out_path.name:<30}  {len(combined):>7,} rows  ({len(chunks)} files)")

    print(f"\nDone — {len(groups)} groups written to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
