#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# """
# Batch PCAP IP modifier.
# Reads all PCAPs in an input folder, filters packets based on allowed IPs,
# rewrites source/destination IPs, and saves results into an output folder.

# Usage:
#     python3 ip_change_folder.py <input_folder> <output_folder>
# """

import os
import sys
from scapy.all import rdpcap, wrpcap, IP, IPv6, TCP, UDP

# === CONFIGURATION ===

# Match packets only if src ∈ old_src_list AND dst ∈ old_dst_list
# old_src_list = ["172.30.1.1", "172.30.1.250", '216.58.199.74', '34.217.4.5', '52.35.215.194', '104.77.174.8', '192.168.1.255', '192.168.1.30', '54.187.116.27', '8.43.85.14', '224.0.0.251', '13.35.146.101', '8.43.85.13', '192.168.1.192', '60.254.148.81', '13.32.126.99', '151.101.30.49', '40.77.226.250', '52.89.173.114', '54.69.84.189', '13.32.126.20', '192.168.1.1', '52.88.72.192', '13.35.146.105', '52.88.71.233', '60.254.148.72', '54.194.229.79', '192.168.1.46', '216.58.199.66', '34.212.240.230', '104.77.174.72', '54.230.245.222', '91.189.92.20', '3.122.49.24', '13.35.146.57', '13.35.146.75', '172.217.25.42', '35.160.231.181', '91.189.92.19', '13.35.146.38', '172.217.167.67', '192.168.1.79', '192.168.1.195', '52.40.98.101', '52.35.21.241', '224.0.0.1', '192.168.1.194', '34.218.159.169', '13.32.126.73', '52.42.83.187', '192.168.1.6', '117.18.237.29', '54.230.245.204', '54.148.123.234', '192.168.1.193', '151.101.2.49', '35.160.78.190', '34.214.89.204', '52.33.113.226', '91.189.89.199', '52.26.235.130', '192.168.1.191', '192.168.1.152', '172.217.167.74', '54.68.141.132', '23.1.240.136', '172.217.25.138', '34.210.150.241', '13.35.146.115', '54.187.176.55', '52.36.71.24', '192.168.1.103', '13.35.146.92', '91.189.91.26', '91.189.88.152', '13.35.146.12', '13.35.146.61', '192.168.1.133', '52.18.210.215', '13.32.126.41', '91.189.92.38', '13.35.146.48', '91.189.92.41', '255.255.255.255', '192.168.1.250', '192.168.1.190', '35.244.179.255', '13.35.146.89', '52.27.23.108', '192.168.1.17', '34.212.55.103', '216.58.199.42', '54.230.245.11', '54.187.144.104', '54.201.6.28']
# old_dst_list = ["172.30.1.250", "172.30.1.1", '216.58.199.74', '34.217.4.5', '52.35.215.194', '104.77.174.8', '192.168.1.255', '192.168.1.30', '54.187.116.27', '8.43.85.14', '224.0.0.251', '13.35.146.101', '8.43.85.13', '192.168.1.192', '60.254.148.81', '13.32.126.99', '151.101.30.49', '40.77.226.250', '52.89.173.114', '54.69.84.189', '13.32.126.20', '192.168.1.1', '52.88.72.192', '13.35.146.105', '52.88.71.233', '60.254.148.72', '54.194.229.79', '192.168.1.46', '216.58.199.66', '34.212.240.230', '104.77.174.72', '54.230.245.222', '91.189.92.20', '3.122.49.24', '13.35.146.57', '13.35.146.75', '172.217.25.42', '35.160.231.181', '91.189.92.19', '13.35.146.38', '172.217.167.67', '192.168.1.79', '192.168.1.195', '52.40.98.101', '52.35.21.241', '224.0.0.1', '192.168.1.194', '34.218.159.169', '13.32.126.73', '52.42.83.187', '192.168.1.6', '117.18.237.29', '54.230.245.204', '54.148.123.234', '192.168.1.193', '151.101.2.49', '35.160.78.190', '34.214.89.204', '52.33.113.226', '91.189.89.199', '52.26.235.130', '192.168.1.191', '192.168.1.152', '172.217.167.74', '54.68.141.132', '23.1.240.136', '172.217.25.138', '34.210.150.241', '13.35.146.115', '54.187.176.55', '52.36.71.24', '192.168.1.103', '13.35.146.92', '91.189.91.26', '91.189.88.152', '13.35.146.12', '13.35.146.61', '192.168.1.133', '52.18.210.215', '13.32.126.41', '91.189.92.38', '13.35.146.48', '91.189.92.41', '255.255.255.255', '192.168.1.250', '192.168.1.190', '35.244.179.255', '13.35.146.89', '52.27.23.108', '192.168.1.17', '34.212.55.103', '216.58.199.42', '54.230.245.11', '54.187.144.104', '54.201.6.28']

# old_src_list = ["172.30.1.1", "172.30.1.250"]
# old_dst_list = ["172.30.1.250", "172.30.1.1"]

old_src_list = ["192.168.72.135"]
old_dst_list = ["12.1.1.2"]

# Rewrite to these
new_src = "10.1.2.14"
new_dst = "12.1.1.100"


# === PROCESS ONE PCAP ===
def process_pcap(input_path, output_path):
    print(f"[INFO] Processing: {input_path}")

    try:
        pkts = rdpcap(input_path)
    except Exception as e:
        print(f"[ERROR] Could not read PCAP {input_path}: {e}")
        return False

    filtered_pkts = []
    total = len(pkts)

    for pkt in pkts:

        # IPv4 -----------------------------------------------------------------
        if IP in pkt:
            ip = pkt[IP]

            if ip.src not in old_src_list or ip.dst not in old_dst_list:
                continue  # skip packet

            # Rewrite
            ip.src = new_src
            ip.dst = new_dst

            # Fix checksums
            if hasattr(ip, "len"): del ip.len
            if hasattr(ip, "chksum"): del ip.chksum
            if TCP in pkt: del pkt[TCP].chksum
            elif UDP in pkt: del pkt[UDP].chksum

            filtered_pkts.append(pkt)

        # IPv6 -----------------------------------------------------------------
        elif IPv6 in pkt:
            ip6 = pkt[IPv6]

            if ip6.src not in old_src_list or ip6.dst not in old_dst_list:
                continue

            ip6.src = new_src
            ip6.dst = new_dst

            # Fix transport checksums
            if TCP in pkt: del pkt[TCP].chksum
            elif UDP in pkt: del pkt[UDP].chksum

            filtered_pkts.append(pkt)

    if not filtered_pkts:
        print(f"[WARN] No matching packets in {input_path}. File skipped.")
        return False

    try:
        wrpcap(output_path, filtered_pkts)
        print(f"[OK] Wrote {len(filtered_pkts)} / {total} packets → {output_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to write PCAP {output_path}: {e}")
        return False


# === MAIN ===
def main():
    if len(sys.argv) != 3:
        print("Usage:")
        print("   python3 modify_pcap_folder.py <input_folder> <output_folder>")
        sys.exit(1)

    input_folder = sys.argv[1]
    output_folder = sys.argv[2]

    if not os.path.isdir(input_folder):
        print(f"[ERROR] Input folder does not exist: {input_folder}")
        sys.exit(1)

    os.makedirs(output_folder, exist_ok=True)

    pcap_files = [f for f in os.listdir(input_folder)
                  if f.lower().endswith((".pcap", ".pcapng"))]

    if not pcap_files:
        print(f"[WARN] No PCAP files found in: {input_folder}")
        sys.exit(0)

    print(f"[INFO] Found {len(pcap_files)} PCAP files.")

    for fname in pcap_files:
        in_path = os.path.join(input_folder, fname)
        out_path = os.path.join(output_folder, fname)

        # Skip if output already exists
        if os.path.exists(out_path):
            print(f"[SKIP] Output already exists → {out_path}")
            continue

        ok = process_pcap(in_path, out_path)
        if not ok:
            print(f"[ALERT] Failed to process {fname}. Continuing…")

    print("[INFO] Done.")


if __name__ == "__main__":
    main()
