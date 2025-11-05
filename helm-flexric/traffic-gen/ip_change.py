#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Nov  4 11:34:19 2025

@author: omer24
"""

from scapy.all import *

# Input/output filenames
input_pcap = "ENCODER_hap.pcap"
output_pcap = "ENCODER_hap_modified.pcap"

# IPs to replace
old_src = "192.168.70.135"   # replace with the original source IP to modify
old_dst = "192.168.70.145"   # replace with the original destination IP to modify
new_src = "10.1.2.14"      # replace with desired new source IP
new_dst = "12.1.1.100"      # replace with desired new destination IP

pkts = rdpcap(input_pcap)

for pkt in pkts:
    # ---- IPv4 ----
    if IP in pkt:
        ip = pkt[IP]
        if ip.src == old_src:
            ip.src = new_src
        if ip.dst == old_dst:
            ip.dst = new_dst

        # Let Scapy recompute header lengths/checksums
        if hasattr(ip, "len"):
            del ip.len
        if hasattr(ip, "chksum"):
            del ip.chksum

        # Recompute transport checksums if present
        if TCP in pkt:
            del pkt[TCP].chksum
        elif UDP in pkt:
            del pkt[UDP].chksum

    # ---- IPv6 (optional) ----
    elif IPv6 in pkt:
        ip6 = pkt[IPv6]
        if ip6.src == old_src:
            ip6.src = new_src
        if ip6.dst == old_dst:
            ip6.dst = new_dst

        # IPv6 has no header checksum, just fix transport
        if TCP in pkt:
            del pkt[TCP].chksum
        elif UDP in pkt:
            del pkt[UDP].chksum

wrpcap(output_pcap, pkts)
