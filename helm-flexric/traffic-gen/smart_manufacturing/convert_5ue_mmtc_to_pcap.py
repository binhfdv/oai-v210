#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Convert 5-UE mMTC traffic CSV to PCAP (raw IP, no Ethernet header).
Designed for 5-UE mMTC slice scenario with IPs: 12.1.1.100 - 12.1.1.104

Usage:
    # Process entire CSV
    python3 convert_5ue_to_pcap.py ue1_5ue_traffic.csv ue_pcaps_5ue/ue1.pcap --ue UE1

    # Process in 20% chunks (recommended for large files)
    python3 convert_5ue_to_pcap.py ue1_5ue_traffic.csv ue_pcaps_5ue/ue1 --ue UE1 --chunks 5

    # Process a specific chunk only
    python3 convert_5ue_to_pcap.py ue1_5ue_traffic.csv ue_pcaps_5ue/ue1.pcap --ue UE1 --chunk 1 --total-chunks 5
"""

import os
import sys
import csv
import argparse
from scapy.all import IP, UDP, TCP, Raw, PcapWriter

MAPPING_FILE = 'device_to_5ue_mmtc_mapping.csv'

UE_IPS = {
    'UE1': '12.1.1.100',  # Secondary Robots A
    'UE2': '12.1.1.101',  # Secondary Robots B
    'UE3': '12.1.1.102',  # Press Operations
    'UE4': '12.1.1.103',  # Feeding Mechanisms
    'UE5': '12.1.1.104',  # Monitoring & Transport
}

def load_device_to_ue_mapping(mapping_file=MAPPING_FILE):
    if not os.path.exists(mapping_file):
        print(f"[WARN] Mapping file {mapping_file} not found. Using source UE only.")
        return None
    device_to_ue = {}
    with open(mapping_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            device_to_ue[row['Device Name']] = row['UE']
    print(f"[INFO] Loaded device-to-UE mapping for {len(device_to_ue)} devices")
    return device_to_ue

def determine_protocol(message_type, communication_type):
    msg_lower = message_type.lower()
    if msg_lower == "ack":
        return "TCP"
    if any(k in msg_lower for k in ["camera", "statistics", "quality"]):
        return "TCP"
    if communication_type == "p":
        return "UDP"
    return "UDP"

def build_packet(src_ip, dst_ip, proto, size, timestamp):
    """Build a raw IP packet (no Ethernet header) for TUN interface replay."""
    ip_layer = IP(src=src_ip, dst=dst_ip)
    l4 = TCP(sport=12345, dport=8080, flags="PA") if proto == "TCP" else UDP(sport=12345, dport=9999)
    pkt = ip_layer / l4

    cur_len = len(pkt)
    target_size = int(float(size))

    # Cap at TUN interface MTU (1500 bytes)
    MAX_PACKET_SIZE = 1500
    if target_size > MAX_PACKET_SIZE:
        target_size = MAX_PACKET_SIZE
    if target_size < cur_len:
        target_size = cur_len

    pad_len = target_size - cur_len
    if pad_len > 0:
        pkt = pkt / Raw(b"\x00" * pad_len)

    pkt.time = float(timestamp)
    return pkt

def count_csv_rows(csv_path):
    print(f"[INFO] Counting rows in {csv_path}...")
    with open(csv_path, 'r') as f:
        next(f)
        count = sum(1 for _ in f)
    print(f"[INFO] Total rows: {count:,}")
    return count

def process_csv_to_pcap(csv_path, output_pcap, ue_id, device_to_ue, chunk_num=None, total_chunks=None):
    if ue_id not in UE_IPS:
        print(f"[ERROR] Invalid UE ID: {ue_id}. Must be UE1-UE5")
        return 0

    ue_ip = UE_IPS[ue_id]
    print(f"[INFO] Processing {csv_path}")
    print(f"[INFO] Source UE: {ue_id}, IP: {ue_ip}")

    start_row, end_row = 0, None
    if chunk_num is not None and total_chunks is not None:
        total_rows = count_csv_rows(csv_path)
        chunk_size = total_rows // total_chunks
        start_row = (chunk_num - 1) * chunk_size
        end_row = start_row + chunk_size if chunk_num < total_chunks else total_rows
        print(f"[INFO] Processing chunk {chunk_num}/{total_chunks}")
        print(f"[INFO] Rows {start_row:,} to {end_row:,} (of {total_rows:,})")

    packets = []
    packet_count = 0
    total_processed = 0

    try:
        with open(csv_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if total_processed < start_row:
                    total_processed += 1
                    continue
                if end_row is not None and total_processed >= end_row:
                    break
                try:
                    transmitter = row['Transmitter'].strip()
                    receiver = row['Receiver'].strip()
                    message_type = row['Message Type'].strip()
                    comm_type = row['Communication Type'].strip()
                    data_size = row['Data Size'].strip()
                    timestamp = row['Timestamp'].strip()

                    if device_to_ue:
                        tx_ue = device_to_ue.get(transmitter, ue_id)
                        rx_ue = device_to_ue.get(receiver, ue_id)
                        src_ip = UE_IPS.get(tx_ue, ue_ip)
                        dst_ip = UE_IPS.get(rx_ue, ue_ip)
                    else:
                        src_ip = dst_ip = ue_ip

                    proto = determine_protocol(message_type, comm_type)
                    pkt = build_packet(src_ip, dst_ip, proto, data_size, timestamp)
                    packets.append(pkt)
                    packet_count += 1
                    total_processed += 1

                    if packet_count % 100000 == 0:
                        print(f"[PROGRESS] Processed {packet_count:,} packets (row {total_processed:,})...")

                except KeyError as e:
                    print(f"[ERROR] Missing column {e} in row")
                    total_processed += 1
                    continue
                except Exception as e:
                    print(f"[ERROR] Failed to process row: {e}")
                    total_processed += 1
                    continue

    except Exception as e:
        print(f"[ERROR] Failed to read CSV: {e}")
        return 0

    if not packets:
        print("[ERROR] No valid packets created")
        return 0

    try:
        with PcapWriter(output_pcap, linktype=101, sync=True) as writer:
            for pkt in packets:
                writer.write(bytes(pkt))
        print(f"[OK] Wrote {len(packets):,} packets to {output_pcap}")
        return len(packets)
    except Exception as e:
        print(f"[ERROR] Failed writing PCAP: {e}")
        return 0

def main():
    parser = argparse.ArgumentParser(description='Convert 5-UE mMTC CSV to PCAP')
    parser.add_argument('csv_file', help='Input CSV file')
    parser.add_argument('output_pcap', help='Output PCAP file (or base name for chunks)')
    parser.add_argument('--ue', choices=['UE1', 'UE2', 'UE3', 'UE4', 'UE5'], required=True)
    parser.add_argument('--chunks', type=int, help='Split into N chunks')
    parser.add_argument('--chunk', type=int, help='Process only this chunk (1-based)')
    parser.add_argument('--total-chunks', type=int, help='Total chunks (used with --chunk)')
    args = parser.parse_args()

    if not os.path.isfile(args.csv_file):
        print(f"[ERROR] CSV file not found: {args.csv_file}")
        sys.exit(1)
    if args.chunk and not args.total_chunks:
        print("[ERROR] --chunk requires --total-chunks")
        sys.exit(1)
    if args.chunks and (args.chunk or args.total_chunks):
        print("[ERROR] Cannot use --chunks with --chunk/--total-chunks")
        sys.exit(1)

    output_dir = os.path.dirname(args.output_pcap)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    device_to_ue = load_device_to_ue_mapping()

    if args.chunks:
        base_name = args.output_pcap.replace('.pcap', '')
        total_packets = 0
        print(f"\n{'='*60}\nCHUNKED PROCESSING: {args.chunks} files\n{'='*60}\n")
        for chunk_num in range(1, args.chunks + 1):
            output_file = f"{base_name}_part{chunk_num}.pcap"
            print(f"\n{'='*60}\nChunk {chunk_num}/{args.chunks}\n{'='*60}")
            count = process_csv_to_pcap(args.csv_file, output_file, args.ue, device_to_ue, chunk_num, args.chunks)
            total_packets += count
        print(f"\n[OK] Total: {total_packets:,} packets across {args.chunks} files")
        print(f"[INFO] Replay: for i in {{1..{args.chunks}}}; do sudo tcpreplay -i oaitun_{args.ue.lower()} {base_name}_part$i.pcap; done")

    elif args.chunk:
        count = process_csv_to_pcap(args.csv_file, args.output_pcap, args.ue, device_to_ue, args.chunk, args.total_chunks)
        if count == 0:
            sys.exit(1)
        print(f"\n[INFO] Use with: sudo tcpreplay -i oaitun_{args.ue.lower()} {args.output_pcap}")

    else:
        count = process_csv_to_pcap(args.csv_file, args.output_pcap, args.ue, device_to_ue)
        if count == 0:
            sys.exit(1)
        print(f"\n[INFO] Use with: sudo tcpreplay -i oaitun_{args.ue.lower()} {args.output_pcap}")

    print("[INFO] Done!")

if __name__ == "__main__":
    main()
