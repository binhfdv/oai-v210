#!/usr/bin/env python3
"""
trim_pcap.py — Trim or extend a pcap file to a fixed duration.

Usage:
    python3 trim_pcap.py <input.pcap> <duration_seconds> [output.pcap]

If the pcap is longer than duration_seconds  → trim it.
If the pcap is shorter than duration_seconds → duplicate packets (re-timestamped) until the duration is reached.

Output defaults to <input>_<duration>s.pcap if not specified.
"""

import sys
import struct
import os


# ── pcap format constants ──────────────────────────────────────────────────────
GLOBAL_HEADER_FMT  = b'<IHHiIII'   # little-endian magic
GLOBAL_HEADER_SIZE = 24
PACKET_HEADER_SIZE = 16
MAGIC_LE = 0xA1B2C3D4
MAGIC_BE = 0xD4C3B2A1


def read_pcap(path):
    """Read a pcap file. Returns (header_bytes, endian_char, snaplen, linktype, packets).
    Each packet is (ts_sec, ts_usec, orig_len, data_bytes).
    """
    with open(path, 'rb') as f:
        raw_header = f.read(GLOBAL_HEADER_SIZE)

    magic = struct.unpack('<I', raw_header[:4])[0]
    if magic == MAGIC_LE:
        endian = '<'
    elif magic == MAGIC_BE:
        endian = '>'
    else:
        raise ValueError(f"Not a valid pcap file (magic=0x{magic:08X})")

    _, ver_major, ver_minor, thiszone, sigfigs, snaplen, linktype = \
        struct.unpack(endian + 'IHHiIII', raw_header)

    packets = []
    with open(path, 'rb') as f:
        f.read(GLOBAL_HEADER_SIZE)  # skip global header
        while True:
            ph = f.read(PACKET_HEADER_SIZE)
            if len(ph) < PACKET_HEADER_SIZE:
                break
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack(endian + 'IIII', ph)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            packets.append((ts_sec, ts_usec, orig_len, data))

    return raw_header, endian, snaplen, linktype, packets


def write_pcap(path, raw_global_header, endian, packets):
    """Write packets to a pcap file, preserving the original global header."""
    with open(path, 'wb') as f:
        f.write(raw_global_header)
        for ts_sec, ts_usec, orig_len, data in packets:
            incl_len = len(data)
            ph = struct.pack(endian + 'IIII', ts_sec, ts_usec, incl_len, orig_len)
            f.write(ph)
            f.write(data)


def pcap_duration(packets):
    """Return duration in seconds between first and last packet."""
    if len(packets) < 2:
        return 0.0
    first = packets[0][0] + packets[0][1] / 1e6
    last  = packets[-1][0] + packets[-1][1] / 1e6
    return last - first


def trim_pcap(packets, duration_sec):
    """Keep only packets within [t0, t0 + duration_sec]."""
    if not packets:
        return packets
    t0 = packets[0][0] + packets[0][1] / 1e6
    cutoff = t0 + duration_sec
    return [(s, u, o, d) for s, u, o, d in packets
            if (s + u / 1e6) <= cutoff]


def extend_pcap(packets, duration_sec):
    """Duplicate packets (re-timestamped) until total duration >= duration_sec."""
    if not packets:
        return packets

    t0       = packets[0][0] + packets[0][1] / 1e6
    src_dur  = pcap_duration(packets)

    if src_dur <= 0:
        # All packets at same timestamp — just replicate with 1ms spacing
        src_dur = len(packets) * 0.001

    result = list(packets)
    offset = src_dur  # time offset for each copy (seconds)

    while pcap_duration(result) < duration_sec:
        for ts_sec, ts_usec, orig_len, data in packets:
            t_orig  = ts_sec + ts_usec / 1e6
            t_new   = t0 + (t_orig - t0) + offset
            new_sec = int(t_new)
            new_usec = int(round((t_new - new_sec) * 1e6))
            result.append((new_sec, new_usec, orig_len, data))

        offset += src_dur

        # safety: avoid infinite loop if src_dur is tiny
        if offset > duration_sec * 100:
            break

    # trim the tail to exact duration
    return trim_pcap(result, duration_sec)


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 trim_pcap.py <input.pcap> <duration_seconds> [output.pcap]")
        sys.exit(1)

    input_path   = sys.argv[1]
    duration_sec = float(sys.argv[2])

    if len(sys.argv) >= 4:
        output_path = sys.argv[3]
    else:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_{int(duration_sec)}s{ext}"

    print(f"Input:    {input_path}")
    print(f"Target:   {duration_sec}s")
    print(f"Output:   {output_path}")

    raw_header, endian, snaplen, linktype, packets = read_pcap(input_path)
    src_duration = pcap_duration(packets)
    print(f"Source:   {len(packets)} packets, {src_duration:.2f}s")

    if src_duration > duration_sec:
        result = trim_pcap(packets, duration_sec)
        print(f"Trimmed → {len(result)} packets")
    else:
        result = extend_pcap(packets, duration_sec)
        print(f"Extended → {len(result)} packets")

    write_pcap(output_path, raw_header, endian, result)
    print(f"Written:  {output_path}")


if __name__ == '__main__':
    main()
