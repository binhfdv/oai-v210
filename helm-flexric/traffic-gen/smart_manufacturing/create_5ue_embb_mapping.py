#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Create device-to-UE mapping for 5-UE eMBB slice scenario.
Each UE represents a group of devices within the eMBB slice.

IPs: 12.1.1.100 - 12.1.1.104

Usage:
    python3 create_5ue_embb_mapping.py
"""

import csv

UE_GROUPS = {
    'UE1': {
        'ip': '12.1.1.100',
        'role': 'Mobile Units Group 1',
        'devices': [
            'AGV #1',
            'AGV #2',
            'AGV #3',
        ]
    },
    'UE2': {
        'ip': '12.1.1.101',
        'role': 'Mobile Units Group 2',
        'devices': [
            'AGV #4',
            'AGV #5',
        ]
    },
    'UE3': {
        'ip': '12.1.1.102',
        'role': 'Camera Controllers',
        'devices': [
            'CameraController #1',
            'CameraController #2',
            'CameraController #3',
        ]
    },
    'UE4': {
        'ip': '12.1.1.103',
        'role': 'Quality Cameras',
        'devices': [
            'QualityCamera #1',
            'QualityCamera #2',
            'QualityCamera #3',
        ]
    },
    'UE5': {
        'ip': '12.1.1.104',
        'role': 'Quality Nodes',
        'devices': [
            'QualityNode #1',
            'QualityNode #2',
            'QualityNode #3',
        ]
    },
}

def main():
    output_csv = 'device_to_5ue_embb_mapping.csv'
    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Device Name', 'UE', 'IP', 'Role'])
        for ue_id, info in UE_GROUPS.items():
            for device in info['devices']:
                writer.writerow([device, ue_id, info['ip'], info['role']])
    print(f"[OK] Written {output_csv}")

    output_txt = 'device_to_5ue_embb_mapping_summary.txt'
    with open(output_txt, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("5-UE DEVICE GROUP MAPPING (eMBB Slice)\n")
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

    print()
    for ue_id, info in UE_GROUPS.items():
        print(f"{ue_id} ({info['ip']}) - {info['role']}")
        for device in info['devices']:
            print(f"  {device}")
        print()

if __name__ == "__main__":
    main()
