"""
Rewrite source/destination IPs in PCAPs from mahdi-embb-oran, mahdi-urllc-oran,
and mmtc/iot_2.pcap so that each of the 5 UEs has its own PCAP with:
  - Source IP  : 12.1.1.10{ue_idx}  (UE's own IP)
  - Dest IP    : round-robin through the other 4 UEs' IPs per packet

Output layout:
  ue_embb/pcaps/vr/ue{1..5}/ue{n}.pcap
  ue_mmtc/pcaps/ton/ue{1..5}/ue{n}.pcap
  ue_urllc/pcaps/ti/ue{1..5}/ue{n}.pcap

Assignment:
  eMBB  vr  : UE1-2 <- video_tele.pcap   | UE3-5 <- video_vr.pcap
  URLLC ti  : UE1-2 <- haptic_tele.pcap  | UE3-5 <- haptic_vr.pcap
  mMTC  ton : iot_2.pcap split 5 equal chunks, one per UE

Source files are Ethernet (linktype=1). Output is Raw IP (linktype=101) to
match the TUN interface replay used by oaitun_ue* — same as convert_5ue_*.py.
Ethernet header (14 bytes) is stripped. Packets capped at 1500 bytes (TUN MTU).
Checksums are zeroed (OAI replayer does not validate them).
"""

import os
import struct
import socket
import itertools

BASE_DIR      = '/home/lapdk/workspace/oai-v210/helm-flexric/traffic-gen'
SM_DIR        = f'{BASE_DIR}/smart_manufacturing'
PCAP_DIR      = f'{BASE_DIR}/pcap'

UE_IPS        = [f'12.1.1.{100 + i}' for i in range(5)]   # UE1..UE5
NUM_UES       = 5
MAX_PKT_SIZE  = 1500   # TUN interface MTU (matches convert_5ue_*.py)

# Global header for linktype=101 (Raw IP), little-endian, µs resolution
RAW_IP_GLOBAL_HDR = struct.pack('<IHHiIII',
    0xa1b2c3d4,   # magic
    2, 4,         # version
    0,            # timezone
    0,            # timestamp accuracy
    65535,        # snaplen
    101           # linktype = Raw IP
)


# ── Low-level PCAP read/write ──────────────────────────────────────────────────

def read_pcap(path):
    """Read an Ethernet pcap. Returns (endian, [(ts_sec, ts_usec, data), ...])."""
    with open(path, 'rb') as f:
        raw = f.read()

    magic = struct.unpack('<I', raw[:4])[0]
    if magic == 0xa1b2c3d4:
        endian = '<'
    elif magic == 0xd4c3b2a1:
        endian = '>'
    else:
        raise ValueError(f'Unknown pcap magic: {hex(magic)} in {path}')

    packets = []
    offset = 24
    while offset + 16 <= len(raw):
        ts_sec, ts_usec, cap_len, orig_len = struct.unpack(endian + 'IIII', raw[offset:offset+16])
        offset += 16
        data = raw[offset:offset+cap_len]
        offset += cap_len
        packets.append((ts_sec, ts_usec, data))

    return endian, packets


def write_pcap_raw_ip(path, packets):
    """Write a Raw IP (linktype=101) pcap — no Ethernet header."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(RAW_IP_GLOBAL_HDR)
        for ts_sec, ts_usec, data in packets:
            cap_len = len(data)
            f.write(struct.pack('<IIII', ts_sec, ts_usec, cap_len, cap_len))
            f.write(data)


# ── Packet conversion ──────────────────────────────────────────────────────────

def ip_to_bytes(ip_str):
    return socket.inet_aton(ip_str)


def eth_to_raw_ip(data, src_ip_bytes, dst_ip_bytes):
    """Strip Ethernet header, rewrite IPs, cap at MAX_PKT_SIZE, zero checksums.

    Input : Ethernet frame (linktype=1)
    Output: Raw IP packet (linktype=101), or None if not IPv4
    """
    if len(data) < 34:        # Ethernet(14) + IP header(20) minimum
        return None
    eth_type = struct.unpack('!H', data[12:14])[0]
    if eth_type != 0x0800:    # not IPv4 — skip (e.g. ARP)
        return None

    # Strip Ethernet header → raw IP packet
    ip_pkt = bytearray(data[14:])

    ihl = (ip_pkt[0] & 0x0F) * 4
    if len(ip_pkt) < ihl:
        return None

    # Cap total length at MAX_PKT_SIZE
    if len(ip_pkt) > MAX_PKT_SIZE:
        ip_pkt = ip_pkt[:MAX_PKT_SIZE]
        # Update IP total length field (bytes 2-3)
        struct.pack_into('!H', ip_pkt, 2, MAX_PKT_SIZE)

    # Rewrite src (bytes 12-15) and dst (bytes 16-19) in IP header
    ip_pkt[12:16] = src_ip_bytes
    ip_pkt[16:20] = dst_ip_bytes

    # Zero IP checksum (bytes 10-11)
    ip_pkt[10:12] = b'\x00\x00'

    # Zero transport checksum
    proto = ip_pkt[9]
    transport_offset = ihl
    if proto == 6 and len(ip_pkt) >= transport_offset + 18:    # TCP chksum at +16
        ip_pkt[transport_offset + 16: transport_offset + 18] = b'\x00\x00'
    elif proto == 17 and len(ip_pkt) >= transport_offset + 8:  # UDP chksum at +6
        ip_pkt[transport_offset + 6: transport_offset + 8] = b'\x00\x00'

    return bytes(ip_pkt)


def rewrite_packets(packets, src_ip, dst_ips):
    """Convert Ethernet packets to Raw IP, rewriting IPs.
    src=src_ip, dst cycles round-robin through dst_ips.
    Non-IPv4 frames are dropped.
    """
    src_bytes = ip_to_bytes(src_ip)
    dst_cycle = itertools.cycle([ip_to_bytes(d) for d in dst_ips])
    rewritten = []
    for ts_sec, ts_usec, data in packets:
        dst_bytes = next(dst_cycle)
        ip_pkt = eth_to_raw_ip(data, src_bytes, dst_bytes)
        if ip_pkt is not None:
            rewritten.append((ts_sec, ts_usec, ip_pkt))
    return rewritten


# ── Helpers ────────────────────────────────────────────────────────────────────

def other_ips(ue_idx):
    """Return the 4 IPs of all UEs except ue_idx."""
    return [UE_IPS[i] for i in range(NUM_UES) if i != ue_idx]


def split_packets(packets, n):
    """Split packet list into n roughly equal chunks."""
    size = len(packets) // n
    chunks = []
    for i in range(n):
        start = i * size
        end = start + size if i < n - 1 else len(packets)
        chunks.append(packets[start:end])
    return chunks


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # ── eMBB / vr ─────────────────────────────────────────────────────────────
    print('\n=== eMBB / vr ===')
    tele_path = f'{PCAP_DIR}/mahdi-embb-oran/video_tele.pcap'
    vr_path   = f'{PCAP_DIR}/mahdi-embb-oran/video_vr.pcap'
    out_embb  = f'{SM_DIR}/ue_embb/pcaps/vr'

    _, pkts_tele = read_pcap(tele_path)
    _, pkts_vr   = read_pcap(vr_path)
    print(f'  video_tele.pcap : {len(pkts_tele)} packets')
    print(f'  video_vr.pcap   : {len(pkts_vr)} packets')

    # UE1-2 → video_tele, UE3-5 → video_vr
    for ue_idx, pkts in [
        (0, pkts_tele), (1, pkts_tele),
        (2, pkts_vr),   (3, pkts_vr), (4, pkts_vr),
    ]:
        out_pkt  = rewrite_packets(pkts, UE_IPS[ue_idx], other_ips(ue_idx))
        out_path = os.path.join(out_embb, f'ue{ue_idx+1}', f'ue{ue_idx+1}.pcap')
        write_pcap_raw_ip(out_path, out_pkt)
        print(f'  Written {len(out_pkt):>7} packets → {out_path}')

    # ── URLLC / ti ────────────────────────────────────────────────────────────
    print('\n=== URLLC / ti ===')
    ht_path   = f'{PCAP_DIR}/mahdi-urllc-oran/haptic_tele.pcap'
    hv_path   = f'{PCAP_DIR}/mahdi-urllc-oran/haptic_vr.pcap'
    out_urllc = f'{SM_DIR}/ue_urllc/pcaps/ti'

    _, pkts_ht = read_pcap(ht_path)
    _, pkts_hv = read_pcap(hv_path)
    print(f'  haptic_tele.pcap: {len(pkts_ht)} packets')
    print(f'  haptic_vr.pcap  : {len(pkts_hv)} packets')

    # UE1-2 → haptic_tele, UE3-5 → haptic_vr
    for ue_idx, pkts in [
        (0, pkts_ht), (1, pkts_ht),
        (2, pkts_hv), (3, pkts_hv), (4, pkts_hv),
    ]:
        out_pkt  = rewrite_packets(pkts, UE_IPS[ue_idx], other_ips(ue_idx))
        out_path = os.path.join(out_urllc, f'ue{ue_idx+1}', f'ue{ue_idx+1}.pcap')
        write_pcap_raw_ip(out_path, out_pkt)
        print(f'  Written {len(out_pkt):>7} packets → {out_path}')

    # ── mMTC / ton ────────────────────────────────────────────────────────────
    print('\n=== mMTC / ton ===')
    iot_path = f'{PCAP_DIR}/mmtc/iot_2.pcap'
    out_mmtc = f'{SM_DIR}/ue_mmtc/pcaps/ton'

    _, pkts_iot = read_pcap(iot_path)
    print(f'  iot_2.pcap      : {len(pkts_iot)} packets → split into 5 chunks')

    for ue_idx, chunk in enumerate(split_packets(pkts_iot, NUM_UES)):
        out_pkt  = rewrite_packets(chunk, UE_IPS[ue_idx], other_ips(ue_idx))
        out_path = os.path.join(out_mmtc, f'ue{ue_idx+1}', f'ue{ue_idx+1}.pcap')
        write_pcap_raw_ip(out_path, out_pkt)
        print(f'  Written {len(out_pkt):>7} packets → {out_path}')

    print('\nDone.')


if __name__ == '__main__':
    main()
