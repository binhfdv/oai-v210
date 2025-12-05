#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Update PCAP by filtering packets based on IP lists
and replacing source/destination IPs.
"""

from scapy.all import *

# Input/output filenames
input_pcap = "mmtc.pcap"
output_pcap = "mmtc_modified_UL.pcap"

# IP lists to match (packets not matching will be deleted)
old_src_list = ["172.30.1.1"]
old_dst_list = ["172.30.1.250"]

# New IPs for rewriting
new_src = "10.1.2.14"
new_dst = "12.1.1.100"

pkts = rdpcap(input_pcap)
filtered_pkts = []

for pkt in pkts:

    # IPv4 ----------------------------
    if IP in pkt:
        ip = pkt[IP]

        # Keep only packets whose src and dst match the lists
        if ip.src not in old_src_list or ip.dst not in old_dst_list:
            continue  # skip this packet (delete it)

        # Replace IPs
        ip.src = new_src
        ip.dst = new_dst

        # Recompute fields
        if hasattr(ip, "len"):
            del ip.len
        if hasattr(ip, "chksum"):
            del ip.chksum

        if TCP in pkt:
            del pkt[TCP].chksum
        elif UDP in pkt:
            del pkt[UDP].chksum

        filtered_pkts.append(pkt)

    # IPv6 ----------------------------
    elif IPv6 in pkt:
        ip6 = pkt[IPv6]

        # Keep only packets with matching IPs
        if ip6.src not in old_src_list or ip6.dst not in old_dst_list:
            continue

        ip6.src = new_src
        ip6.dst = new_dst

        if TCP in pkt:
            del pkt[TCP].chksum
        elif UDP in pkt:
            del pkt[UDP].chksum

        filtered_pkts.append(pkt)

# Save only the packets that matched and were modified
wrpcap(output_pcap, filtered_pkts)

print(f"Done. Kept {len(filtered_pkts)} packets out of {len(pkts)}.")
