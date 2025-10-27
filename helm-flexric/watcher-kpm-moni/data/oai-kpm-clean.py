#!/usr/bin/env python3
import csv
import os
import sys
from pathlib import Path

def clean_kpm_file(input_file, output_file):
    with open(input_file, "r") as f_in, open(output_file, "w", newline="") as f_out:
        reader = csv.DictReader(f_in)
        # Prepare new header without 'UE ID type'
        fields = [field for field in reader.fieldnames if field != "UE ID type"]
        writer = csv.DictWriter(f_out, fieldnames=fields)
        writer.writeheader()

        # Keep CU rows by ran_ue_id
        cu_rows = {}

        for row in reader:
            ue_type = row.get("UE ID type", "")
            ran_ue_id = row.get("ran_ue_id", "")
            if not ran_ue_id:
                continue  # skip if no UE ID

            if "CU" in ue_type:
                # Save CU row per UE
                cu_rows[ran_ue_id] = row
            elif "DU" in ue_type:
                merged = row.copy()
                # Merge with corresponding CU row if exists
                if ran_ue_id in cu_rows:
                    cu_row = cu_rows[ran_ue_id]
                    # Automatically merge all CU columns except 'UE ID type' and ran_ue_id
                    for key, value in cu_row.items():
                        if key not in ("UE ID type", "ran_ue_id") and value:
                            merged[key] = value
                    # Remove CU row from buffer to avoid reuse
                    del cu_rows[ran_ue_id]
                merged.pop("UE ID type", None)
                writer.writerow(merged)

def main():
    if len(sys.argv) != 3:
        print("Usage: oai-kpm-clean <input-raw-dir> <output-raw-dir>")
        sys.exit(1)

    input_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_files = list(input_dir.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {input_dir}")
        sys.exit(1)

    for csv_file in csv_files:
        output_file = output_dir / csv_file.name
        print(f"Cleaning {csv_file} -> {output_file}")
        clean_kpm_file(csv_file, output_file)

if __name__ == "__main__":
    main()
