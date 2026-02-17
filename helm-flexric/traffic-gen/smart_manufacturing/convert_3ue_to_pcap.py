#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Convert UE-specific CSV files to PCAP with correct UE IP addresses.
Designed for 3-UE deployment with IPs: 12.1.1.100, 12.1.1.101, 12.1.1.102

Usage:
    # Process entire CSV
    python3 convert_3ue_to_pcap.py ue1_traffic.csv ue_pcaps/ue1.pcap

    # Process in 20% chunks (recommended for large files)
    python3 convert_3ue_to_pcap.py ue1_traffic.csv ue_pcaps/ue1 --chunks 5
    # Creates: ue1_part1.pcap, ue1_part2.pcap, ..., ue1_part5.pcap

    # Process specific chunk only
    python3 convert_3ue_to_pcap.py ue1_traffic.csv ue_pcaps/ue1.pcap --chunk 1 --total-chunks 5

Or auto-detect UE from filename:
    python3 convert_3ue_to_pcap.py ue1_traffic.csv output.pcap --auto
"""

import os
import sys
import csv
import argparse
from scapy.all import Ether, IP, UDP, TCP, Raw, wrpcap

# UE IP mapping for OAI deployment
UE_IPS = {
    'UE1': '12.1.1.100',  # URLLC - Critical Production
    'UE2': '12.1.1.101',  # eMBB - Mobile & Vision
    'UE3': '12.1.1.102',  # mMTC - Monitoring & Sensors
}

UE_MACS = {
    'UE1': '02:00:0c:01:01:64',  # From 12.1.1.100
    'UE2': '02:00:0c:01:01:65',  # From 12.1.1.101
    'UE3': '02:00:0c:01:01:66',  # From 12.1.1.102
}

def detect_ue_from_filename(filename):
    """Auto-detect UE number from filename."""
    basename = os.path.basename(filename).lower()
    if 'ue1' in basename or 'urllc' in basename:
        return 'UE1'
    elif 'ue2' in basename or 'embb' in basename:
        return 'UE2'
    elif 'ue3' in basename or 'mmtc' in basename:
        return 'UE3'
    return None

def determine_protocol(message_type, communication_type):
    """
    Determine L4 protocol based on message type and communication type.
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

def build_packet(src_ip, dst_ip, src_mac, dst_mac, proto, size, timestamp):
    """
    Build a network packet with specified source and destination.
    For inter-UE traffic, source and dest IPs/MACs will differ.
    """
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
    target_size = int(float(size))

    # Cap at maximum jumbo frame size (9000 bytes)
    # Very large messages (like 1MB camera data) would be fragmented in reality
    MAX_PACKET_SIZE = 9000
    if target_size > MAX_PACKET_SIZE:
        target_size = MAX_PACKET_SIZE

    if target_size < cur_len:
        target_size = cur_len

    pad_len = target_size - cur_len
    if pad_len > 0:
        pkt = pkt / Raw(b"\x00" * pad_len)

    # Set timestamp
    pkt.time = float(timestamp)

    return pkt

def count_csv_rows(csv_path):
    """Count total rows in CSV (excluding header)."""
    print(f"[INFO] Counting rows in {csv_path}...")
    with open(csv_path, 'r') as f:
        # Skip header
        next(f)
        count = sum(1 for _ in f)
    print(f"[INFO] Total rows: {count:,}")
    return count

def load_device_to_ue_mapping(mapping_file='device_to_ue_mapping.csv'):
    """Load device-to-UE mapping from CSV."""
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

def process_csv_to_pcap(csv_path, output_pcap, ue_id, chunk_num=None, total_chunks=None):
    """
    Process UE-specific CSV and create PCAP file with UE IP.

    Args:
        csv_path: Path to input CSV
        output_pcap: Path to output PCAP
        ue_id: UE identifier (UE1, UE2, or UE3)
        chunk_num: Which chunk to process (1-based, None = process all)
        total_chunks: Total number of chunks (None = process all)

    Returns:
        Number of packets processed
    """
    if ue_id not in UE_IPS:
        print(f"[ERROR] Invalid UE ID: {ue_id}. Must be UE1, UE2, or UE3")
        return 0

    ue_ip = UE_IPS[ue_id]
    ue_mac = UE_MACS[ue_id]

    print(f"[INFO] Processing {csv_path}")
    print(f"[INFO] Source UE: {ue_id}, IP: {ue_ip}, MAC: {ue_mac}")

    # Load device-to-UE mapping for inter-UE traffic
    device_to_ue = load_device_to_ue_mapping()

    # Calculate chunk boundaries if chunking
    start_row = 0
    end_row = None

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
                # Skip rows before start_row
                if total_processed < start_row:
                    total_processed += 1
                    continue

                # Stop if we've reached end_row
                if end_row is not None and total_processed >= end_row:
                    break

                try:
                    transmitter = row['Transmitter'].strip()
                    receiver = row['Receiver'].strip()
                    message_type = row['Message Type'].strip()
                    comm_type = row['Communication Type'].strip()
                    data_size = row['Data Size'].strip()
                    timestamp = row['Timestamp'].strip()

                    # Determine source and dest IPs based on device-to-UE mapping
                    if device_to_ue:
                        tx_ue = device_to_ue.get(transmitter, ue_id)
                        rx_ue = device_to_ue.get(receiver, ue_id)
                        src_ip = UE_IPS[tx_ue]
                        dst_ip = UE_IPS[rx_ue]
                        src_mac = UE_MACS[tx_ue]
                        dst_mac = UE_MACS[rx_ue]
                    else:
                        # Fallback: use source UE for both
                        src_ip = dst_ip = ue_ip
                        src_mac = dst_mac = ue_mac

                    # Determine protocol
                    proto = determine_protocol(message_type, comm_type)

                    # Build packet with correct source/dest
                    pkt = build_packet(src_ip, dst_ip, src_mac, dst_mac, proto, data_size, timestamp)
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
        print(f"[ERROR] No valid packets created")
        return 0

    try:
        wrpcap(output_pcap, packets)
        print(f"[OK] Wrote {len(packets):,} packets to {output_pcap}")
        print(f"[INFO] All traffic uses {ue_id} IP: {ue_ip}")
        return len(packets)
    except Exception as e:
        print(f"[ERROR] Failed writing PCAP: {e}")
        return 0

def main():
    parser = argparse.ArgumentParser(
        description='Convert UE-specific CSV to PCAP with correct UE IPs'
    )
    parser.add_argument('csv_file', help='Input CSV file')
    parser.add_argument('output_pcap', help='Output PCAP file (or base name for chunks)')
    parser.add_argument('--ue', choices=['UE1', 'UE2', 'UE3'],
                        help='UE identifier (UE1, UE2, or UE3)')
    parser.add_argument('--auto', action='store_true',
                        help='Auto-detect UE from filename')
    parser.add_argument('--chunks', type=int,
                        help='Split into N chunks (e.g., 5 for 20%% each). Creates multiple PCAP files.')
    parser.add_argument('--chunk', type=int,
                        help='Process only this chunk number (1-based, requires --total-chunks)')
    parser.add_argument('--total-chunks', type=int,
                        help='Total number of chunks (used with --chunk)')

    args = parser.parse_args()

    if not os.path.isfile(args.csv_file):
        print(f"[ERROR] CSV file not found: {args.csv_file}")
        sys.exit(1)

    # Validate chunk arguments
    if args.chunk and not args.total_chunks:
        print("[ERROR] --chunk requires --total-chunks")
        sys.exit(1)

    if args.chunks and (args.chunk or args.total_chunks):
        print("[ERROR] Cannot use --chunks with --chunk/--total-chunks")
        sys.exit(1)

    # Determine UE
    ue_id = args.ue
    if args.auto or not ue_id:
        ue_id = detect_ue_from_filename(args.csv_file)
        if not ue_id:
            print("[ERROR] Could not auto-detect UE from filename.")
            print("Use --ue UE1|UE2|UE3 to specify manually.")
            sys.exit(1)
        print(f"[INFO] Auto-detected: {ue_id}")

    # Create output directory if needed
    output_dir = os.path.dirname(args.output_pcap)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Process in chunks or single file
    if args.chunks:
        # Process all chunks
        print(f"\n{'='*80}")
        print(f"CHUNKED PROCESSING: Creating {args.chunks} PCAP files")
        print(f"{'='*80}\n")

        total_packets = 0
        base_name = args.output_pcap.replace('.pcap', '')

        for chunk_num in range(1, args.chunks + 1):
            output_file = f"{base_name}_part{chunk_num}.pcap"

            print(f"\n{'='*80}")
            print(f"Processing Chunk {chunk_num}/{args.chunks}")
            print(f"{'='*80}")

            count = process_csv_to_pcap(args.csv_file, output_file, ue_id,
                                       chunk_num, args.chunks)
            total_packets += count

            if count == 0:
                print(f"[WARN] Chunk {chunk_num} produced no packets")

        print(f"\n{'='*80}")
        print(f"ALL CHUNKS COMPLETE")
        print(f"{'='*80}")
        print(f"[INFO] Total packets across all chunks: {total_packets:,}")
        print(f"[INFO] Created {args.chunks} PCAP files:")
        for i in range(1, args.chunks + 1):
            print(f"  - {base_name}_part{i}.pcap")
        print(f"\n[INFO] To replay all chunks:")
        print(f"  for i in {{1..{args.chunks}}}; do")
        print(f"    sudo tcpreplay -i oaitun_{ue_id.lower()} {base_name}_part$i.pcap")
        print(f"  done")

    elif args.chunk:
        # Process single chunk
        count = process_csv_to_pcap(args.csv_file, args.output_pcap, ue_id,
                                    args.chunk, args.total_chunks)

        if count > 0:
            print("\n[INFO] Done!")
            print(f"[INFO] PCAP file: {args.output_pcap}")
            print(f"[INFO] Chunk {args.chunk} of {args.total_chunks}")
            print(f"[INFO] Use with: sudo tcpreplay -i oaitun_{ue_id.lower()} {args.output_pcap}")
        else:
            print("\n[ERROR] Failed to create PCAP")
            sys.exit(1)

    else:
        # Process entire file
        count = process_csv_to_pcap(args.csv_file, args.output_pcap, ue_id)

        if count > 0:
            print("\n[INFO] Done!")
            print(f"[INFO] PCAP file: {args.output_pcap}")
            print(f"[INFO] Use with: sudo tcpreplay -i oaitun_{ue_id.lower()} {args.output_pcap}")
        else:
            print("\n[ERROR] Failed to create PCAP")
            sys.exit(1)

if __name__ == "__main__":
    main()
