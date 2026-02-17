#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Split data_communications.csv by source UE (transmitter).
Only keeps inter-UE traffic (transmitter UE ≠ receiver UE).

Usage:
    python3 split_by_source_ue.py data_communications.csv device_to_ue_mapping.csv
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
        print("    python3 split_by_source_ue.py data_communications.csv device_to_ue_mapping.csv")
        sys.exit(1)

    data_csv = sys.argv[1]
    mapping_csv = sys.argv[2]

    print(f"[INFO] Loading device-to-UE mapping from {mapping_csv}")
    device_to_ue = load_device_mapping(mapping_csv)
    print(f"[INFO] Loaded mapping for {len(device_to_ue)} devices")

    print(f"[INFO] Processing {data_csv}")

    # Statistics
    stats = defaultdict(int)
    skipped_intra_ue = 0
    total_rows = 0

    # Output file handles
    output_files = {
        'UE1': open('ue1_traffic.csv', 'w', newline=''),
        'UE2': open('ue2_traffic.csv', 'w', newline=''),
        'UE3': open('ue3_traffic.csv', 'w', newline='')
    }

    writers = {}

    try:
        with open(data_csv, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            header = reader.fieldnames

            # Create writers
            for ue_id, file_handle in output_files.items():
                writers[ue_id] = csv.DictWriter(file_handle, fieldnames=header)
                writers[ue_id].writeheader()

            for row in reader:
                total_rows += 1

                transmitter = row['Transmitter'].strip()
                receiver = row['Receiver'].strip()

                # Get UE assignments
                tx_ue = device_to_ue.get(transmitter)
                rx_ue = device_to_ue.get(receiver)

                if not tx_ue or not rx_ue:
                    print(f"[WARN] Unknown device: TX={transmitter} ({tx_ue}), RX={receiver} ({rx_ue})")
                    continue

                # Only keep inter-UE traffic (transmitter UE ≠ receiver UE)
                if tx_ue == rx_ue:
                    skipped_intra_ue += 1
                    continue

                # Write to file based on transmitter's UE
                writers[tx_ue].writerow(row)
                stats[tx_ue] += 1

                if total_rows % 1000000 == 0:
                    print(f"[PROGRESS] Processed {total_rows:,} rows...")

    finally:
        # Close all files
        for f in output_files.values():
            f.close()

    print(f"\n[OK] Processing complete. Total rows: {total_rows:,}")
    print(f"[INFO] Skipped intra-UE traffic: {skipped_intra_ue:,} rows")

    # Print statistics
    print("\n" + "=" * 80)
    print("INTER-UE TRAFFIC SPLIT BY SOURCE UE")
    print("=" * 80)

    ue1_count = stats['UE1']
    ue2_count = stats['UE2']
    ue3_count = stats['UE3']
    total_inter = ue1_count + ue2_count + ue3_count

    print(f"\nUE1 as source (inter-UE):  {ue1_count:>10,} messages ({ue1_count/total_inter*100:>5.1f}%)")
    print(f"UE2 as source (inter-UE):  {ue2_count:>10,} messages ({ue2_count/total_inter*100:>5.1f}%)")
    print(f"UE3 as source (inter-UE):  {ue3_count:>10,} messages ({ue3_count/total_inter*100:>5.1f}%)")
    print(f"Total inter-UE:            {total_inter:>10,} messages")

    print("\n" + "=" * 80)
    print("OUTPUT FILES (Inter-UE traffic only):")
    print("=" * 80)
    print(f"  ue1_traffic.csv - {ue1_count:,} messages (UE1 → UE2/UE3)")
    print(f"  ue2_traffic.csv - {ue2_count:,} messages (UE2 → UE1/UE3)")
    print(f"  ue3_traffic.csv - {ue3_count:,} messages (UE3 → UE1/UE2)")
    print("=" * 80)

    print("\n[INFO] Next step: Convert to PCAPs with correct source/dest IPs")
    print("    python3 convert_3ue_to_pcap.py ue1_traffic.csv ue_pcaps/ue1 --chunks 5")
    print("    python3 convert_3ue_to_pcap.py ue2_traffic.csv ue_pcaps/ue2 --chunks 5")
    print("    python3 convert_3ue_to_pcap.py ue3_traffic.csv ue_pcaps/ue3 --chunks 5")

if __name__ == "__main__":
    main()
