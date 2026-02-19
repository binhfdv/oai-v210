#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Split data_communications.csv for the 5-UE scenario.
Keeps only traffic where BOTH transmitter and receiver are in the 5-UE device group mapping.
Each output CSV contains traffic where transmitter belongs to that UE group.

Usage:
    python3 split_by_5ue.py data_communications.csv device_to_5ue_mapping.csv
"""

import sys
import csv
from collections import defaultdict

def load_device_mapping(mapping_file):
    """Load device-to-UE mapping from CSV."""
    device_to_ue = {}
    with open(mapping_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            device_to_ue[row['Device Name']] = row['UE']
    return device_to_ue

def main():
    if len(sys.argv) != 3:
        print("Usage:")
        print("    python3 split_by_5ue.py data_communications.csv device_to_5ue_mapping.csv")
        sys.exit(1)

    data_csv = sys.argv[1]
    mapping_csv = sys.argv[2]

    print(f"[INFO] Loading 5-UE device mapping from {mapping_csv}")
    device_to_ue = load_device_mapping(mapping_csv)
    known_devices = set(device_to_ue.keys())
    print(f"[INFO] Loaded {len(known_devices)} devices across 5 UEs")

    print(f"[INFO] Processing {data_csv}")

    stats = defaultdict(int)
    skipped = 0
    total_rows = 0

    ue_ids = ['UE1', 'UE2', 'UE3', 'UE4', 'UE5']

    output_files = {ue: open(f"{ue.lower()}_5ue_traffic.csv", 'w', newline='') for ue in ue_ids}
    writers = {}

    try:
        with open(data_csv, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            header = reader.fieldnames

            for ue_id, fh in output_files.items():
                writers[ue_id] = csv.DictWriter(fh, fieldnames=header)
                writers[ue_id].writeheader()

            for row in reader:
                total_rows += 1

                transmitter = row['Transmitter'].strip()
                receiver = row['Receiver'].strip()

                # Skip if either device is not in the 5-UE mapping
                if transmitter not in known_devices or receiver not in known_devices:
                    skipped += 1
                    continue

                tx_ue = device_to_ue[transmitter]
                rx_ue = device_to_ue[receiver]

                # Write to file based on transmitter's UE group
                writers[tx_ue].writerow(row)
                stats[f"{tx_ue}->{rx_ue}"] += 1
                stats[tx_ue] += 1

                if total_rows % 1000000 == 0:
                    print(f"[PROGRESS] Processed {total_rows:,} rows...")

    finally:
        for f in output_files.values():
            f.close()

    print(f"\n[OK] Processing complete. Total rows: {total_rows:,}")
    print(f"[INFO] Skipped (devices outside 5-UE group): {skipped:,} rows")

    total_kept = sum(stats[ue] for ue in ue_ids)

    print("\n" + "=" * 80)
    print("TRAFFIC SPLIT BY 5-UE GROUPS")
    print("=" * 80)
    for ue_id in ue_ids:
        count = stats[ue_id]
        print(f"  {ue_id}: {count:>10,} messages as source")

    print(f"\n  Total kept: {total_kept:,} messages")

    print("\n" + "=" * 80)
    print("INTER-GROUP COMMUNICATION BREAKDOWN")
    print("=" * 80)
    for flow, count in sorted(stats.items()):
        if '->' in flow:
            print(f"  {flow:<15} {count:>10,} messages")

    print("\n" + "=" * 80)
    print("OUTPUT FILES:")
    print("=" * 80)
    for ue_id in ue_ids:
        print(f"  {ue_id.lower()}_5ue_traffic.csv  - {stats[ue_id]:,} messages")
    print("=" * 80)

    print("\n[INFO] Next step: Convert to PCAPs")
    for ue_id in ue_ids:
        n = ue_id[-1]
        print(f"    python3 convert_5ue_to_pcap.py {ue_id.lower()}_5ue_traffic.csv ue_pcaps_5ue/{ue_id.lower()}.pcap --ue {ue_id}")

if __name__ == "__main__":
    main()
