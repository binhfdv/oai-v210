#!/usr/bin/env python3
import argparse
import os
import csv
from scapy.all import rdpcap, IP, TCP, UDP, ICMP, DNS

# ----------------------------------------
# Map human readable protocol names
# ----------------------------------------
PROTO_MAP = {
    "tcp": TCP,
    "udp": UDP,
    "icmp": ICMP,
    "dns": DNS,
    "mdns": DNS,  # same layer
    "ssdp": UDP,
    "coap": UDP,
    "mqtt": TCP,
    "http": TCP,
    "https": TCP,
    "tls": TCP,
    "dtls": UDP,
    "snmp": UDP,
    "modbus": TCP,
    "any": None
}

def process_pcap(appname, pcap_file, protocol, writer):
    """Read packets from a pcap file and write cleaned data to CSV."""

    print(f"📄 Processing {pcap_file} ...")

    try:
        packets = rdpcap(pcap_file)
    except Exception as e:
        print(f"❌ Failed to read {pcap_file}: {e}")
        return

    proto_filter = PROTO_MAP.get(protocol.lower())

    count = 0
    for idx, pkt in enumerate(packets, start=1):

        # Must contain IP layer
        if not pkt.haslayer(IP):
            continue

        # Filter by protocol
        if proto_filter is not None and not pkt.haslayer(proto_filter):
            continue

        # Determine protocol name
        if pkt.haslayer(TCP):
            proto_name = "TCP"
        elif pkt.haslayer(UDP):
            proto_name = "UDP"
        elif pkt.haslayer(ICMP):
            proto_name = "ICMP"
        else:
            proto_name = "OTHER"

        count += 1
        writer.writerow([
            appname,
            count,
            float(pkt.time),
            pkt[IP].src,
            pkt[IP].dst,
            proto_name,
            len(pkt)
        ])

    print(f"✅ {pcap_file}: {count} packets written.\n")


def main():
    parser = argparse.ArgumentParser(description="Clean PCAPs and export to CSV.")
    parser.add_argument("--pcap", help="Path to a pcap file or directory", required=True)
    parser.add_argument("--appname", help="Application name tag", required=True)
    parser.add_argument("--protocol", help="Protocol filter: tcp/udp/icmp/any", default="any")

    parser.add_argument("--output", help="Output CSV file", default="output.csv")

    args = parser.parse_args()

    # Validate protocol
    if args.protocol.lower() not in PROTO_MAP:
        print("❌ Invalid protocol. Use: tcp / udp / icmp / any")
        return

    # Collect pcap files
    if os.path.isdir(args.pcap):
        pcaps = sorted([
            os.path.join(args.pcap, f)
            for f in os.listdir(args.pcap)
            if f.endswith(".pcap")
        ])
    else:
        pcaps = [args.pcap]

    if not pcaps:
        print("❌ No pcap files found.")
        return

    # Write to CSV
    with open(args.output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Appname", "No.", "Time", "Source", "Destination", "Protocol", "Length"])

        for pcap_file in pcaps:
            process_pcap(args.appname, pcap_file, args.protocol, writer)

    print(f"🎉 Finished. CSV saved to: {args.output}")


if __name__ == "__main__":
    main()
