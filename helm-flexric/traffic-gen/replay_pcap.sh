#!/usr/bin/env bash
set -euo pipefail

# === Configurable parameters ===
GW="10.1.3.18"        # Gateway IP which is UPF IP
IFACE="net1"          # Interface used for sending which is ext-dn/traffic-server interface
OUT="rewrite.pcap"    # Output file name (temporary rewritten file)

# === Input check ===
if [ $# -lt 1 ]; then
  echo "Usage: $0 <pcap_file>"
  exit 1
fi

PCAP="$1"

# === Get MAC addresses dynamically ===
ping 12.1.1.100 -I net1 -c 3 > /dev/null 2>&1
GW_MAC=$(ip neigh show dev "$IFACE" | awk -v gw="$GW" '$1==gw {print $3}')
SRC_MAC=$(ip link show "$IFACE" | awk '/link\/ether/ {print $2}')

if [ -z "$GW_MAC" ]; then
  echo "❌ Could not find gateway MAC for $GW of UPF on interface $IFACE"
  exit 1
fi

echo "🧭 Interface:     $IFACE"
echo "🌐 UPF Gateway:   $GW ($GW_MAC)"
echo "📤 Source:        $SRC_MAC"
echo "📁 Input:         $PCAP"
echo "📁 Output:        $OUT"
echo

echo "=== Rewrite L2 headers ==="
tcprewrite \
  --infile="$PCAP" \
  --outfile="$OUT" \
  --enet-dmac="$GW_MAC" \
  --enet-smac="$SRC_MAC" \
  --fixcsum
echo "✅ Rewrite complete."
echo

echo "=== Replay ==="
tcpreplay -i "$IFACE" --timer=nano "$OUT"

echo "✅ Replay complete."
