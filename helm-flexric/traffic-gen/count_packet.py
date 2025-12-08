#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from scapy.all import PcapReader

def count_packets_in_pcap(path):
    """Count packets using a streaming reader (safest for large files)."""
    count = 0
    try:
        with PcapReader(path) as pcap:
            for _ in pcap:
                count += 1
    except Exception as e:
        print(f"[ERROR] Failed to read {path}: {e}")
        return None
    return count

def main():
    if len(sys.argv) != 2:
        print("Usage:")
        print("   python3 count_packets_in_folder.py <pcap_folder>")
        sys.exit(1)

    folder = sys.argv[1]

    if not os.path.isdir(folder):
        print(f"[ERROR] Folder does not exist: {folder}")
        sys.exit(1)

    pcap_files = [f for f in os.listdir(folder) if f.lower().endswith(".pcap")]

    if not pcap_files:
        print(f"[WARN] No PCAP files found in folder: {folder}")
        sys.exit(0)

    print(f"[INFO] Found {len(pcap_files)} pcap files.\n")

    total_packets = 0

    for filename in pcap_files:
        path = os.path.join(folder, filename)
        print(f"[INFO] Reading {filename} ...")

        count = count_packets_in_pcap(path)
        if count is None:
            print(f"[SKIP] Could not count packets in {filename}")
            continue

        print(f"[OK] {filename}: {count} packets\n")
        total_packets += count

    print("=========================================")
    print(f"[RESULT] Total packets across all pcaps: {total_packets}")
    print("=========================================")

if __name__ == "__main__":
    main()
