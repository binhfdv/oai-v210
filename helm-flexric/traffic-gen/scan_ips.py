"""
Scan all pcap files in a folder and print all unique src/dst IPs with packet counts.
Usage: python3 scan_ips.py <pcap_folder>
"""
import sys
import collections
from pathlib import Path
from scapy.all import rdpcap, IP, IPv6

folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
files  = sorted(folder.glob("*.pcap"))

if not files:
    sys.exit(f"No pcap files found in {folder}")

print(f"Scanning {len(files)} files in {folder} ...")

src_ips = collections.Counter()
dst_ips = collections.Counter()

for i, f in enumerate(files, 1):
    print(f"  [{i}/{len(files)}] {f.name}", end="\r", flush=True)
    try:
        for pkt in rdpcap(str(f)):
            if IP in pkt:
                src_ips[pkt[IP].src] += 1
                dst_ips[pkt[IP].dst] += 1
            elif IPv6 in pkt:
                src_ips[pkt[IPv6].src] += 1
                dst_ips[pkt[IPv6].dst] += 1
    except Exception as e:
        print(f"\n  [ERR] {f.name}: {e}")

src_out = "./scan_src_ips.txt"
dst_out = "./scan_dst_ips.txt"

with open(src_out, "w") as f:
    for ip, count in src_ips.most_common():
        f.write(f"{ip:<45} {count:>10} packets\n")

with open(dst_out, "w") as f:
    for ip, count in dst_ips.most_common():
        f.write(f"{ip:<45} {count:>10} packets\n")

print(f"Source IPs      → {src_out}")
print(f"Destination IPs → {dst_out}")
