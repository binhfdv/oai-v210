#!/bin/bash
# Replay all PCAP files in a UE folder using tcpreplay
#
# Usage:
#   ./replay.sh <ue_folder> <interface> [speed]
#
# Examples:
#   ./replay.sh ue1 oaitun_ue1
#   ./replay.sh ue2 oaitun_ue2 10
#   ./replay.sh ue3 oaitun_ue3 5

if [ $# -lt 2 ]; then
    echo "Usage: $0 <ue_folder> <interface> [speed]"
    echo ""
    echo "  ue_folder  - Folder containing PCAP files (e.g., ue1, ue2, ue3)"
    echo "  interface  - Network interface to replay on (e.g., oaitun_ue1)"
    echo "  speed      - Replay speed multiplier (default: 10)"
    echo ""
    echo "Examples:"
    echo "  $0 ue1 oaitun_ue1"
    echo "  $0 ue2 oaitun_ue2 10"
    echo "  $0 ue3 oaitun_ue3 5"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UE_FOLDER="$SCRIPT_DIR/$1"
INTERFACE="$2"
SPEED="${3:-10}"

if [ ! -d "$UE_FOLDER" ]; then
    echo "[ERROR] Folder not found: $UE_FOLDER"
    exit 1
fi

PCAP_FILES=$(ls "$UE_FOLDER"/*.pcap 2>/dev/null | sort)

if [ -z "$PCAP_FILES" ]; then
    echo "[ERROR] No PCAP files found in $UE_FOLDER"
    exit 1
fi

COUNT=$(echo "$PCAP_FILES" | wc -l)
echo "[INFO] Found $COUNT PCAP file(s) in $1/"
echo "[INFO] Interface: $INTERFACE"
echo "[INFO] Speed: ${SPEED}x"
echo ""

CURRENT=0
for pcap in $PCAP_FILES; do
    CURRENT=$((CURRENT + 1))
    FILENAME=$(basename "$pcap")
    echo "[INFO] Replaying $FILENAME ($CURRENT/$COUNT)..."
    tcpreplay --preload-pcap -i "$INTERFACE" --timer=nano --stats=1 -p "$SPEED" "$pcap"
    echo "[OK] Finished $FILENAME"
done

echo ""
echo "[OK] All $COUNT PCAP files replayed on $INTERFACE"
