#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Split data_communications.csv by slice (intra-slice traffic only).
Only keeps rows where BOTH transmitter and receiver belong to the same slice/UE.

Slices:
  UE1 / URLLC - Critical Production Control
  UE2 / eMBB  - Mobile & Vision
  UE3 / mMTC  - Monitoring & Sensors

Usage:
    python3 split_by_slice.py data_communications.csv device_to_ue_mapping.csv
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
        print("    python3 split_by_slice.py data_communications.csv device_to_ue_mapping.csv")
        sys.exit(1)

    data_csv = sys.argv[1]
    mapping_csv = sys.argv[2]

    print(f"[INFO] Loading device-to-UE mapping from {mapping_csv}")
    device_to_ue = load_device_mapping(mapping_csv)
    print(f"[INFO] Loaded mapping for {len(device_to_ue)} devices")

    print(f"[INFO] Processing {data_csv}")
    print(f"[INFO] Keeping only intra-slice traffic (transmitter UE == receiver UE)")

    stats = defaultdict(int)
    skipped_inter_slice = 0
    total_rows = 0

    output_files = {
        'UE1': open('ue1_intra_traffic.csv', 'w', newline=''),
        'UE2': open('ue2_intra_traffic.csv', 'w', newline=''),
        'UE3': open('ue3_intra_traffic.csv', 'w', newline='')
    }

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

                tx_ue = device_to_ue.get(transmitter)
                rx_ue = device_to_ue.get(receiver)

                if not tx_ue or not rx_ue:
                    print(f"[WARN] Unknown device: TX={transmitter}, RX={receiver}")
                    continue

                # Only keep intra-slice traffic (both devices in same slice)
                if tx_ue != rx_ue:
                    skipped_inter_slice += 1
                    continue

                writers[tx_ue].writerow(row)
                stats[tx_ue] += 1

                if total_rows % 1000000 == 0:
                    print(f"[PROGRESS] Processed {total_rows:,} rows...")

    finally:
        for f in output_files.values():
            f.close()

    print(f"\n[OK] Processing complete. Total rows: {total_rows:,}")
    print(f"[INFO] Skipped inter-slice traffic: {skipped_inter_slice:,} rows")

    ue1_count = stats['UE1']
    ue2_count = stats['UE2']
    ue3_count = stats['UE3']
    total_intra = ue1_count + ue2_count + ue3_count

    print("\n" + "=" * 80)
    print("INTRA-SLICE TRAFFIC SPLIT BY SLICE")
    print("=" * 80)
    print(f"\nUE1 / URLLC (Critical Production): {ue1_count:>10,} messages ({ue1_count/total_rows*100:>5.1f}% of total)")
    print(f"UE2 / eMBB  (Mobile & Vision):     {ue2_count:>10,} messages ({ue2_count/total_rows*100:>5.1f}% of total)")
    print(f"UE3 / mMTC  (Monitoring):           {ue3_count:>10,} messages ({ue3_count/total_rows*100:>5.1f}% of total)")
    print(f"Total intra-slice:                  {total_intra:>10,} messages ({total_intra/total_rows*100:>5.1f}% of total)")
    print(f"Skipped inter-slice:                {skipped_inter_slice:>10,} messages ({skipped_inter_slice/total_rows*100:>5.1f}% of total)")

    print("\n" + "=" * 80)
    print("OUTPUT FILES (Intra-slice traffic only):")
    print("=" * 80)
    print(f"  ue1_slice_traffic.csv  - {ue1_count:,} messages (URLLC devices only)")
    print(f"  ue2_slice_traffic.csv  - {ue2_count:,} messages (eMBB devices only)")
    print(f"  ue3_slice_traffic.csv  - {ue3_count:,} messages (mMTC devices only)")
    print("=" * 80)

if __name__ == "__main__":
    main()
