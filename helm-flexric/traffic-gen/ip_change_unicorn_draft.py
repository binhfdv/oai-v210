#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Update PCAP by filtering packets based on IP lists
and replacing source/destination IPs.
"""

from scapy.all import *

# Input/output filenames
input_pcap = "urllc_106_PCAPdroid.pcap"
output_pcap = "urllc_106_PCAPdroid_modified.pcap"

# New IPs to rewrite everything to
new_src = "10.1.2.14"
new_dst = "12.1.1.100"

pkts = rdpcap(input_pcap)

for pkt in pkts:

    # IPv4 --------------------------------------------------
    if IP in pkt:
        pkt[IP].src = new_src
        pkt[IP].dst = new_dst

        # Recompute IP + transport checksums
        del pkt[IP].len
        del pkt[IP].chksum
        if TCP in pkt:
            del pkt[TCP].chksum
        elif UDP in pkt:
            del pkt[UDP].chksum

    # IPv6 --------------------------------------------------
    elif IPv6 in pkt:
        pkt[IPv6].src = new_src
        pkt[IPv6].dst = new_dst

        # Transport-layer checksum fix
        if TCP in pkt:
            del pkt[TCP].chksum
        elif UDP in pkt:
            del pkt[UDP].chksum

wrpcap(output_pcap, pkts)
print("Done: all packet IPs rewritten.")