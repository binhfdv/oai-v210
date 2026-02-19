#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Create device-to-UE mapping for 5-UE mMTC slice scenario.
Each UE represents a group of devices within the mMTC slice.

IPs: 12.1.1.100 - 12.1.1.104

Usage:
    python3 create_5ue_mmtc_mapping.py
"""

import csv

UE_GROUPS = {
    'UE1': {
        'ip': '12.1.1.100',
        'role': 'Secondary Robots A',
        'devices': [
            'RobotController 3 #1',
            'RobotController 3 #2',
            'RobotController 3 #3',
            'RobotController 4 #1',
            'RobotController 4 #2',
            'RobotController 4 #3',
        ]
    },
    'UE2': {
        'ip': '12.1.1.101',
        'role': 'Secondary Robots B',
        'devices': [
            'RobotController 5 #1',
            'RobotController 5 #2',
            'RobotController 5 #3',
            'RobotController 6 #1',
            'RobotController 6 #2',
            'RobotController 6 #3',
            'RobotController 7 #1',
            'RobotController 7 #2',
            'RobotController 7 #3',
        ]
    },
    'UE3': {
        'ip': '12.1.1.102',
        'role': 'Press Operations',
        'devices': [
            'UWICORE Press 1 #1',
            'UWICORE Press 1 #2',
            'UWICORE Press 1 #3',
            'UWICORE Press 2 #1',
            'UWICORE Press 2 #2',
            'UWICORE Press 2 #3',
            'UWICORE Press 3 #1',
            'UWICORE Press 3 #2',
            'UWICORE Press 3 #3',
        ]
    },
    'UE4': {
        'ip': '12.1.1.103',
        'role': 'Feeding Mechanisms',
        'devices': [
            'FeedPressRobot 1 #1',
            'FeedPressRobot 1 #2',
            'FeedPressRobot 1 #3',
            'FeedPressRobot 2 #1',
            'FeedPressRobot 2 #2',
            'FeedPressRobot 2 #3',
            'FeedPressRobot 3 #1',
            'FeedPressRobot 3 #2',
            'FeedPressRobot 3 #3',
            'FeedPressRobot 4 #1',
            'FeedPressRobot 4 #2',
            'FeedPressRobot 4 #3',
            'FeedLineRobot 1 #1',
            'FeedLineRobot 1 #2',
            'FeedLineRobot 1 #3',
            'FeedLineRobot 2 #1',
            'FeedLineRobot 2 #2',
            'FeedLineRobot 2 #3',
            'FeederPressLine 1 #1',
            'FeederPressLine 1 #2',
            'FeederPressLine 1 #3',
            'FeederPressLine 2 #1',
            'FeederPressLine 2 #2',
            'FeederPressLine 2 #3',
        ]
    },
    'UE5': {
        'ip': '12.1.1.104',
        'role': 'Monitoring & Transport',
        'devices': [
            'GlobalMonitorSystem',
            'InFromConveyor #1',
            'InFromConveyor #2',
            'InFromConveyor #3',
            'OutFromConveyor #1',
            'OutFromConveyor #2',
            'OutFromConveyor #3',
            'InToConveyor #1',
            'InToConveyor #2',
            'InToConveyor #3',
            'OutToConveyor #1',
            'OutToConveyor #2',
            'OutToConveyor #3',
            'OutShelfFromConveyor #1',
            'OutShelfToConveyor #1',
            'InboundShelf #1',
            'InboundShelf #2',
            'OutboundShelf #1',
            'OutboundShelf #2',
            'OutboundLine 1 #1',
            'OutboundLine 1 #2',
            'OutboundLine 1 #3',
            'OutboundLine 2 #1',
            'OutboundLine 2 #2',
            'OutboundLine 2 #3',
            'FailLineRobot #1',
            'FailLineRobot #2',
            'FailLineRobot #3',
        ]
    },
}

def main():
    output_csv = 'device_to_5ue_mmtc_mapping.csv'
    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Device Name', 'UE', 'IP', 'Role'])
        for ue_id, info in UE_GROUPS.items():
            for device in info['devices']:
                writer.writerow([device, ue_id, info['ip'], info['role']])
    print(f"[OK] Written {output_csv}")

    output_txt = 'device_to_5ue_mmtc_mapping_summary.txt'
    with open(output_txt, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("5-UE DEVICE GROUP MAPPING (mMTC Slice)\n")
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
