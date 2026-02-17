#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Convert data_communications.csv to PCAP file(s) for smart manufacturing traffic simulation.

Usage:
    python3 convert_to_pcap.py data_communications.csv output.pcap
    python3 convert_to_pcap.py data_communications.csv output_dir/ --split 1000000
"""

import os
import sys
import csv
import hashlib
from scapy.all import Ether, IP, UDP, TCP, Raw, wrpcap
from collections import defaultdict

def device_name_to_ip(device_name, device_to_ip_map, ip_counter):
    """
    Map device name to a unique IP address in 10.0.0.0/8 range.
    Uses consistent hashing to ensure same device always gets same IP.
    """
    if device_name not in device_to_ip_map:
        # Use hash to create deterministic IP assignment
        hash_val = int(hashlib.md5(device_name.encode()).hexdigest()[:6], 16)
        # Map to 10.x.x.x range (avoiding 10.0.0.0 and 10.255.255.255)
        octet2 = ((hash_val >> 16) & 0xFF) % 255 + 1
        octet3 = ((hash_val >> 8) & 0xFF)
        octet4 = (hash_val & 0xFF) % 254 + 1
        ip = f"10.{octet2}.{octet3}.{octet4}"
        device_to_ip_map[device_name] = ip
    return device_to_ip_map[device_name]

def ip_to_pseudo_mac(ip_str):
    """Create reproducible locally-administered MAC from IPv4."""
    octets = [int(x) for x in ip_str.split('.')]
    return "02:00:%02x:%02x:%02x:%02x" % tuple(octets)

def determine_protocol(message_type, communication_type):
    """
    Determine L4 protocol based on message type and communication type.
    - Periodic (p) messages use UDP
    - ACK messages use TCP
    - Large data transfers (QualityCameraData, Statistics) use TCP
    - Everything else uses UDP
    """
    msg_lower = message_type.lower()

    # TCP for acknowledgments
    if msg_lower == "ack":
        return "TCP"

    # TCP for large data transfers
    if any(keyword in msg_lower for keyword in ["camera", "statistics", "quality"]):
        return "TCP"

    # UDP for periodic status updates
    if communication_type == "p":
        return "UDP"

    # Default to UDP
    return "UDP"

def build_packet(src_ip, dst_ip, proto, size, timestamp):
    """Build a network packet with given parameters."""
    src_mac = ip_to_pseudo_mac(src_ip)
    dst_mac = ip_to_pseudo_mac(dst_ip)

    eth = Ether(src=src_mac, dst=dst_mac)
    ip_layer = IP(src=src_ip, dst=dst_ip)

    # Build L4 layer
    if proto.upper() == "TCP":
        l4 = TCP(sport=12345, dport=8080, flags="PA")  # Push + ACK for data
    else:  # UDP
        l4 = UDP(sport=12345, dport=9999)

    pkt = eth / ip_layer / l4

    # Calculate padding needed
    cur_len = len(pkt)
    target_size = int(size)

    if target_size < cur_len:
        # If requested size is smaller than minimum, use minimum
        target_size = cur_len

    pad_len = target_size - cur_len
    if pad_len > 0:
        pkt = pkt / Raw(b"\x00" * pad_len)

    # Set timestamp
    pkt.time = float(timestamp)

    return pkt

def process_csv_to_pcap(csv_path, output_pcap, max_packets=None, skip_rows=0):
    """
    Process data_communications.csv and create PCAP file.

    Args:
        csv_path: Path to input CSV
        output_pcap: Path to output PCAP
        max_packets: Maximum number of packets to include (None = all)
        skip_rows: Number of data rows to skip from beginning

    Returns:
        Number of packets processed
    """
    packets = []
    device_to_ip_map = {}
    ip_counter = [1]  # Mutable counter

    print(f"[INFO] Processing {csv_path}")
    if skip_rows > 0:
        print(f"[INFO] Skipping first {skip_rows} data rows")
    if max_packets:
        print(f"[INFO] Limiting to {max_packets} packets")

    packet_count = 0
    skipped_count = 0

    try:
        with open(csv_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                # Skip rows if requested
                if skipped_count < skip_rows:
                    skipped_count += 1
                    continue

                # Stop if max packets reached
                if max_packets and packet_count >= max_packets:
                    break

                try:
                    transmitter = row['Transmitter'].strip()
                    receiver = row['Receiver'].strip()
                    message_type = row['Message Type'].strip()
                    comm_type = row['Communication Type'].strip()
                    data_size = row['Data Size'].strip()
                    timestamp = row['Timestamp'].strip()

                    # Map device names to IPs
                    src_ip = device_name_to_ip(transmitter, device_to_ip_map, ip_counter)
                    dst_ip = device_name_to_ip(receiver, device_to_ip_map, ip_counter)

                    # Determine protocol
                    proto = determine_protocol(message_type, comm_type)

                    # Build packet
                    pkt = build_packet(src_ip, dst_ip, proto, data_size, timestamp)
                    packets.append(pkt)
                    packet_count += 1

                    if packet_count % 100000 == 0:
                        print(f"[PROGRESS] Processed {packet_count} packets...")

                except KeyError as e:
                    print(f"[ERROR] Missing column {e} in row: {row}")
                    continue
                except Exception as e:
                    print(f"[ERROR] Failed to process row: {e}")
                    continue

    except Exception as e:
        print(f"[ERROR] Failed to read CSV: {e}")
        return 0

    if not packets:
        print(f"[ERROR] No valid packets created")
        return 0

    try:
        wrpcap(output_pcap, packets)
        print(f"[OK] Wrote {len(packets)} packets to {output_pcap}")
        print(f"[INFO] Mapped {len(device_to_ip_map)} unique devices to IP addresses")
        return len(packets)
    except Exception as e:
        print(f"[ERROR] Failed writing PCAP: {e}")
        return 0

def split_to_multiple_pcaps(csv_path, output_dir, packets_per_file):
    """
    Split large CSV into multiple PCAP files.

    Args:
        csv_path: Path to input CSV
        output_dir: Directory for output PCAP files
        packets_per_file: Number of packets per PCAP file
    """
    os.makedirs(output_dir, exist_ok=True)

    # Count total rows first
    with open(csv_path, 'r') as f:
        total_rows = sum(1 for _ in f) - 1  # Subtract header

    print(f"[INFO] Total data rows: {total_rows:,}")

    file_num = 0
    processed = 0

    while processed < total_rows:
        file_num += 1
        output_pcap = os.path.join(output_dir, f"smart_manufacturing_part{file_num:03d}.pcap")

        print(f"\n[INFO] Creating {output_pcap}")
        count = process_csv_to_pcap(
            csv_path,
            output_pcap,
            max_packets=packets_per_file,
            skip_rows=processed
        )

        if count == 0:
            break

        processed += count
        print(f"[INFO] Total processed: {processed:,} / {total_rows:,}")

def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  Single PCAP:")
        print("    python3 convert_to_pcap.py data_communications.csv output.pcap")
        print("\n  Split into multiple PCAPs:")
        print("    python3 convert_to_pcap.py data_communications.csv output_dir/ --split 1000000")
        print("\n  Split examples:")
        print("    --split 1000000    # 1 million packets per file")
        print("    --split 500000     # 500k packets per file")
        sys.exit(1)

    csv_path = sys.argv[1]
    output_path = sys.argv[2]

    if not os.path.isfile(csv_path):
        print(f"[ERROR] CSV file not found: {csv_path}")
        sys.exit(1)

    # Check for split mode
    if len(sys.argv) >= 4 and sys.argv[3] == "--split":
        if len(sys.argv) < 5:
            print("[ERROR] --split requires packet count argument")
            sys.exit(1)

        try:
            packets_per_file = int(sys.argv[4])
        except ValueError:
            print(f"[ERROR] Invalid packet count: {sys.argv[4]}")
            sys.exit(1)

        print(f"[INFO] Split mode: {packets_per_file:,} packets per file")
        split_to_multiple_pcaps(csv_path, output_path, packets_per_file)
    else:
        # Single file mode
        process_csv_to_pcap(csv_path, output_path)

    print("\n[INFO] Done!")

if __name__ == "__main__":
    main()
