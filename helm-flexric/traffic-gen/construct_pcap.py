#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# This will convert all CSV files in input_csv_folder to PCAP files in output_pcap_folder
# python3 make_pcap_from_folder.py input_csv_folder output_pcap_folder


import os
import sys
import csv
import ipaddress
from scapy.all import Ether, IP, UDP, TCP, Raw, wrpcap

def ip_to_pseudo_mac(ip_str):
    """Create reproducible locally-administered MAC from IPv4."""
    octets = [int(x) for x in ipaddress.IPv4Address(ip_str).exploded.split('.')]
    return "02:00:%02x:%02x:%02x:%02x" % tuple(octets)

def build_packet(src_ip, dst_ip, proto, size):
    src_mac = ip_to_pseudo_mac(src_ip)
    dst_mac = ip_to_pseudo_mac(dst_ip)

    eth = Ether(src=src_mac, dst=dst_mac)
    ip = IP(src=src_ip, dst=dst_ip)

    proto_up = proto.strip().upper()
    if proto_up == "TCP":
        l4 = TCP(sport=12345, dport=443, flags="A")
    elif proto_up in ("UDP", "DNS"):
        l4 = UDP(sport=12345, dport=53 if proto_up == "DNS" else 9999)
    else:
        l4 = UDP(sport=12345, dport=9999)

    pkt = eth / ip / l4

    cur_len = len(pkt)
    if size < cur_len:
        print(f"[WARN] desired size {size} < min packet size {cur_len}. Using {cur_len}.")
        return pkt

    pad_len = size - cur_len
    if pad_len > 0:
        pkt = pkt / Raw(b"\x00" * pad_len)

    return pkt

def process_csv(csv_path, output_pcap):
    packets = []
    print(f"[INFO] Processing {csv_path}")

    try:
        with open(csv_path, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            if not reader.fieldnames:
                print(f"[ERROR] Invalid CSV (no header): {csv_path}")
                return False

            for row in reader:
                src = row.get("Source") or row.get("source")
                dst = row.get("Target") or row.get("Destination") or row.get("target") or row.get("destination")
                proto = row.get("Protocol") or row.get("protocol") or "UDP"
                size_field = row.get("Size") or row.get("Length") or row.get("length")
                time_field = row.get("Time") or row.get("time") or None

                if not src or not dst or not size_field:
                    print(f"[WARN] Skipping invalid row: {row}")
                    continue

                try:
                    size = int(size_field)
                except ValueError:
                    print(f"[WARN] Invalid size, skipping row: {row}")
                    continue

                try:
                    pkt = build_packet(src, dst, proto, size)
                except Exception as e:
                    print(f"[ERROR] Failed to build packet from row {row}: {e}")
                    continue

                if time_field:
                    try:
                        pkt.time = float(time_field)
                    except ValueError:
                        pass

                packets.append(pkt)

    except Exception as e:
        print(f"[ERROR] Failed to read CSV {csv_path}: {e}")
        return False

    if not packets:
        print(f"[ERROR] No valid packets created from {csv_path}")
        return False

    try:
        wrpcap(output_pcap, packets)
        print(f"[OK] Wrote {len(packets)} packets → {output_pcap}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed writing PCAP {output_pcap}: {e}")
        return False

def main():
    if len(sys.argv) != 3:
        print("Usage:")
        print("   python make_pcap_from_folder.py <input_folder> <output_folder>")
        sys.exit(1)

    input_folder = sys.argv[1]
    output_folder = sys.argv[2]

    if not os.path.isdir(input_folder):
        print(f"[ERROR] Input folder does not exist: {input_folder}")
        sys.exit(1)

    os.makedirs(output_folder, exist_ok=True)

    csv_files = [f for f in os.listdir(input_folder) if f.lower().endswith(".csv")]
    if not csv_files:
        print(f"[WARN] No CSV files found in: {input_folder}")
        sys.exit(0)

    print(f"[INFO] Found {len(csv_files)} CSV files.")

    for csv_file in csv_files:
        csv_path = os.path.join(input_folder, csv_file)

        base = os.path.splitext(csv_file)[0]
        pcap_path = os.path.join(output_folder, base + ".pcap")

        success = process_csv(csv_path, pcap_path)
        if not success:
            print(f"[ALERT] Failed converting {csv_file}, continuing.")

    print("[INFO] Done.")

if __name__ == "__main__":
    main()
