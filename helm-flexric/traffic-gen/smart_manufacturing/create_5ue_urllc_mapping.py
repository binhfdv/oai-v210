#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Create device-to-UE mapping for 5-UE URLLC slice scenario.
Each UE represents a group of devices within the URLLC slice.

IPs: 12.1.1.100 - 12.1.1.104

Usage:
    python3 create_5ue_mapping.py
"""

import csv

# 5-UE device group mapping (URLLC slice devices only)
UE_GROUPS = {
    'UE1': {
        'ip': '12.1.1.100',
        'role': 'Production Line 1 Robots',
        'devices': [
            'RobotController 1 #1',
            'RobotController 1 #2',
            'RobotController 1 #3',
        ]
    },
    'UE2': {
        'ip': '12.1.1.101',
        'role': 'Production Line 2 Robots',
        'devices': [
            'RobotController 2 #1',
            'RobotController 2 #2',
            'RobotController 2 #3',
        ]
    },
    'UE3': {
        'ip': '12.1.1.102',
        'role': 'Storage Inbound Control',
        'devices': [
            'StorageController - In',
            'SC In - AGV Controller',
            'SC In - Crane Controller',
        ]
    },
    'UE4': {
        'ip': '12.1.1.103',
        'role': 'Storage Outbound Control',
        'devices': [
            'StorageController - Out',
            'SC Out - Crane Controller',
        ]
    },
    'UE5': {
        'ip': '12.1.1.104',
        'role': 'Physical Crane Unit',
        'devices': [
            'Single Stacker Crane - In',
            'Single Stacker Crane - Out',
        ]
    },
}

def main():
    # Build device-to-UE lookup
    device_to_ue = {}
    for ue_id, info in UE_GROUPS.items():
        for device in info['devices']:
            device_to_ue[device] = ue_id

    # Write CSV mapping
    output_csv = 'device_to_5ue_mapping.csv'
    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Device Name', 'UE', 'IP', 'Role'])
        for ue_id, info in UE_GROUPS.items():
            for device in info['devices']:
                writer.writerow([device, ue_id, info['ip'], info['role']])

    print(f"[OK] Written {output_csv}")

    # Write human-readable summary
    output_txt = 'device_to_5ue_mapping_summary.txt'
    with open(output_txt, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("5-UE DEVICE GROUP MAPPING (URLLC Slice)\n")
        f.write("=" * 80 + "\n")

        for ue_id, info in UE_GROUPS.items():
            f.write(f"\n{ue_id} ({info['ip']}) - {info['role']}\n")
            f.write("-" * 80 + "\n")
            for device in info['devices']:
                f.write(f"  {device}\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write(f"Total UEs: {len(UE_GROUPS)}\n")
        f.write(f"Total devices: {sum(len(v['devices']) for v in UE_GROUPS.values())}\n")
        f.write("=" * 80 + "\n")

    print(f"[OK] Written {output_txt}")

    # Print to console
    print()
    for ue_id, info in UE_GROUPS.items():
        print(f"{ue_id} ({info['ip']}) - {info['role']}")
        for device in info['devices']:
            print(f"  {device}")
        print()

if __name__ == "__main__":
    main()
