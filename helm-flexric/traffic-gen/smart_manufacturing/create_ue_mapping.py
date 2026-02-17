#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Create device-to-UE mapping for 3-UE deployment.
Maps all 103 devices to one of 3 UEs based on function and traffic patterns.

Usage:
    python3 create_ue_mapping.py data_communications.csv
"""

import sys
import csv
from collections import OrderedDict

# UE1: Critical Production Control (URLLC)
UE1_DEVICES = [
    "StorageController - In",
    "StorageController - Out",
    "SC In - AGV Controller",
    "SC Out - Crane Controller",
    "SC In - Crane Controller",
    "Single Stacker Crane - In",
    "Single Stacker Crane - Out",
    "RobotController 1 #1",
    "RobotController 1 #2",
    "RobotController 1 #3",
    "RobotController 2 #1",
    "RobotController 2 #2",
    "RobotController 2 #3",
]

# UE2: Mobile & Vision Systems (eMBB + Mobility)
UE2_DEVICES = [
    "AGV #1",
    "AGV #2",
    "AGV #3",
    "AGV #4",
    "AGV #5",
    "QualityCamera #1",
    "QualityCamera #2",
    "QualityCamera #3",
    "CameraController #1",
    "CameraController #2",
    "CameraController #3",
    "QualityNode #1",
    "QualityNode #2",
    "QualityNode #3",
]

# UE3: Monitoring & Sensors (mMTC) - everything else
# This will be determined automatically as "not in UE1 or UE2"

def get_ue_assignment(device_name):
    """Determine which UE a device belongs to."""
    if device_name in UE1_DEVICES:
        return "UE1", "URLLC", "Critical Production Control"
    elif device_name in UE2_DEVICES:
        return "UE2", "eMBB", "Mobile & Vision Systems"
    else:
        return "UE3", "mMTC", "Monitoring & Sensors"

def main():
    if len(sys.argv) != 2:
        print("Usage:")
        print("    python3 create_ue_mapping.py data_communications.csv")
        sys.exit(1)

    csv_path = sys.argv[1]

    print(f"[INFO] Reading devices from {csv_path}")

    # Collect all unique devices
    devices = set()
    with open(csv_path, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            devices.add(row['Transmitter'].strip())
            devices.add(row['Receiver'].strip())

    print(f"[INFO] Found {len(devices)} unique devices")

    # Create mapping
    mapping = OrderedDict()
    ue_counts = {"UE1": 0, "UE2": 0, "UE3": 0}

    for device in sorted(devices):
        ue, slice_type, description = get_ue_assignment(device)
        mapping[device] = (ue, slice_type, description)
        ue_counts[ue] += 1

    # Write to CSV
    output_csv = "device_to_ue_mapping.csv"
    with open(output_csv, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Device Name', 'UE', 'Slice Type', 'Description', 'IP Address'])

        # Get IP addresses from device_ip_mapping.txt if it exists
        ip_map = {}
        try:
            with open('device_ip_mapping.txt', 'r') as f:
                for line in f:
                    if line.strip() and not line.startswith('=') and not line.startswith('-') and 'DEVICE NAME' not in line and 'Total devices' not in line:
                        parts = line.strip().split()
                        if len(parts) >= 2 and parts[-2].count('.') == 3:  # Has IP address
                            # Device name is everything except last 2 items (IP and MAC)
                            device_name = ' '.join(parts[:-2])
                            ip_address = parts[-2]
                            ip_map[device_name] = ip_address
        except FileNotFoundError:
            print("[WARN] device_ip_mapping.txt not found, IPs will be empty")

        for device, (ue, slice_type, description) in mapping.items():
            ip_address = ip_map.get(device, "")
            writer.writerow([device, ue, slice_type, description, ip_address])

    print(f"[OK] Mapping written to {output_csv}")

    # Write summary
    summary_file = "device_to_ue_mapping_summary.txt"
    with open(summary_file, 'w') as f:
        f.write("=" * 100 + "\n")
        f.write("3-UE DEPLOYMENT: DEVICE-TO-UE MAPPING SUMMARY\n")
        f.write("=" * 100 + "\n\n")

        for ue_id in ["UE1", "UE2", "UE3"]:
            # Find first device of this UE to get description
            desc = None
            slice_type = None
            for device, (ue, st, d) in mapping.items():
                if ue == ue_id:
                    desc = d
                    slice_type = st
                    break

            f.write(f"\n{ue_id}: {desc} ({slice_type})\n")
            f.write("-" * 100 + "\n")
            f.write(f"{'Device Name':<50} {'IP Address':<20}\n")
            f.write("-" * 100 + "\n")

            count = 0
            for device, (ue, st, d) in mapping.items():
                if ue == ue_id:
                    ip = ip_map.get(device, "N/A")
                    f.write(f"{device:<50} {ip:<20}\n")
                    count += 1

            f.write(f"\nTotal devices in {ue_id}: {count}\n")

        f.write("\n" + "=" * 100 + "\n")
        f.write(f"UE1 (URLLC):  {ue_counts['UE1']} devices\n")
        f.write(f"UE2 (eMBB):   {ue_counts['UE2']} devices\n")
        f.write(f"UE3 (mMTC):   {ue_counts['UE3']} devices\n")
        f.write(f"TOTAL:        {sum(ue_counts.values())} devices\n")
        f.write("=" * 100 + "\n")

    print(f"[OK] Summary written to {summary_file}")

    # Print summary to console
    print("\n" + "=" * 100)
    print("DEVICE-TO-UE MAPPING SUMMARY")
    print("=" * 100)
    print(f"UE1 (URLLC - Critical Production):  {ue_counts['UE1']} devices")
    print(f"UE2 (eMBB - Mobile & Vision):       {ue_counts['UE2']} devices")
    print(f"UE3 (mMTC - Monitoring & Sensors):  {ue_counts['UE3']} devices")
    print(f"TOTAL:                              {sum(ue_counts.values())} devices")
    print("=" * 100)

    print("\n[INFO] Files created:")
    print(f"  - {output_csv} (CSV format)")
    print(f"  - {summary_file} (Human-readable)")

if __name__ == "__main__":
    main()
